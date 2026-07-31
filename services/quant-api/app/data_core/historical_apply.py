"""Hash-bound orchestration for the one approved JM historical apply.

This module is deliberately split into preparation and execution. Packet and
current-fact verification completes before callers construct RQData or
CanonicalStore dependencies with write side effects.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol, Sequence

from app.data_core.contracts import BarFrequency, DatasetKey, DatasetKind
from app.data_core.historical_apply_gate import verify_apply_approval_packet
from app.data_core.historical_apply_receipt import PartialApplyReceiptStore
from app.data_core.historical_sync import MappingSyncResult, SyncResult
from app.data_core.rqdata_adapter import TradingSessionCoverage
from app.data_core.rqdata_adapter import MainMapRow


_CONTINUOUS_DIRECT_FREQUENCIES = (
    BarFrequency.M1,
    BarFrequency.D1,
    BarFrequency.W1,
)
_ACTUAL_DIRECT_FREQUENCIES = (
    BarFrequency.M1,
    BarFrequency.D1,
)


class ApplySynchronizer(Protocol):
    def sync_rank1_mapping(self, **kwargs: Any) -> MappingSyncResult: ...

    def sync(self, **kwargs: Any) -> SyncResult: ...


@dataclass(frozen=True, slots=True)
class PreparedHistoricalApply:
    task_head: str
    plan_digest: str
    start: datetime
    end: datetime
    allowed_actual_contracts: tuple[str, ...]
    canonical_root: Path
    staging_root: Path
    receipt_path: Path
    mapping_trading_days: tuple[date, ...]
    mapping_session_windows: tuple[tuple[date, datetime, datetime], ...]

    def datasets_for_contracts(
        self,
        actual_contracts: Sequence[str],
    ) -> tuple[DatasetKey, ...]:
        normalized = tuple(sorted(set(actual_contracts)))
        if any(item not in self.allowed_actual_contracts for item in normalized):
            raise ValueError("historical_apply_contract_outside_scope")
        continuous = tuple(
            DatasetKey(
                provider="rqdata",
                dataset_kind=DatasetKind.CONTINUOUS,
                symbol="jm",
                contract_or_series="JM.MAIN",
                frequency=frequency,
                adjustment="none",
                schema_version="canonical-bar-v1",
            )
            for frequency in _CONTINUOUS_DIRECT_FREQUENCIES
        )
        actual = tuple(
            DatasetKey(
                provider="rqdata",
                dataset_kind=DatasetKind.ACTUAL_DOMINANT,
                symbol="jm",
                contract_or_series=contract,
                frequency=frequency,
                adjustment="none",
                schema_version="canonical-bar-v1",
            )
            for contract in normalized
            for frequency in _ACTUAL_DIRECT_FREQUENCIES
        )
        return continuous + actual


def prepare_historical_apply(
    packet: Mapping[str, Any],
    *,
    approval_hash: str,
    current_facts: Mapping[str, Any],
    progress_receipt: Mapping[str, Any] | None = None,
) -> PreparedHistoricalApply:
    verify_apply_approval_packet(
        packet,
        approval_hash=approval_hash,
        current_facts=current_facts,
        progress_receipt=progress_receipt,
    )
    facts = packet["bound_facts"]
    scope = facts["scope"]
    write_set = facts["write_set"]
    mapping_plan = facts["mapping_write_plan"]
    state = facts["current_state"]
    contracts = tuple(scope["contract_or_series"])
    return PreparedHistoricalApply(
        task_head=str(facts["task_head"]),
        plan_digest=str(facts["plan_digest"]),
        start=_aware_utc(scope["window"]["start"]),
        end=_aware_utc(scope["window"]["end"]),
        allowed_actual_contracts=tuple(contracts[1:]),
        canonical_root=Path(write_set["canonical_root"]),
        staging_root=Path(write_set["staging_root"]),
        receipt_path=Path(write_set["partial_apply_receipt"]),
        mapping_trading_days=tuple(
            date.fromisoformat(item) for item in mapping_plan["trading_days"]
        ),
        mapping_session_windows=tuple(
            (
                date.fromisoformat(item["trading_day"]),
                _aware_utc(item["start"]),
                _aware_utc(item["end"]),
            )
            for item in state["session_windows"]
        ),
    )


def prepare_historical_apply_roots(
    prepared: PreparedHistoricalApply,
) -> Path:
    """Create only the packet-bound data-core-v2 parent after Gate verification."""
    parent = prepared.canonical_root.parent
    if parent != prepared.staging_root.parent:
        raise ValueError("historical_apply_roots_mismatch")
    anchor = parent.parent
    if not anchor.is_dir() or anchor.is_symlink():
        raise ValueError("historical_apply_root_anchor_invalid")
    try:
        parent.mkdir(mode=0o700, exist_ok=False)
    except FileExistsError:
        pass
    if not parent.is_dir() or parent.is_symlink():
        raise ValueError("historical_apply_root_parent_invalid")
    return parent


def execute_prepared_historical_apply(
    prepared: PreparedHistoricalApply,
    *,
    synchronizer: ApplySynchronizer,
    expected_trading_days: Sequence[date],
    commit: Callable[[], None],
    rollback: Callable[[], None],
    receipt_store: PartialApplyReceiptStore | None = None,
    reconcile_mapping: Callable[[Sequence[MainMapRow]], bool] | None = None,
    reconcile_completed_dataset: Callable[[DatasetKey, Mapping[str, Any]], bool]
    | None = None,
    capture_progress_state_digest: Callable[[], str] | None = None,
    capture_partition_evidence: Callable[[DatasetKey], Sequence[Mapping[str, Any]]]
    | None = None,
) -> dict[str, Any]:
    days = _trading_days(expected_trading_days, prepared)
    if days != prepared.mapping_trading_days:
        raise ValueError("historical_apply_mapping_plan_days_changed")
    try:
        resumed_mapping = (
            receipt_store.completed_mapping()
            if receipt_store is not None
            else None
        )
        if resumed_mapping is not None:
            rows = _mapping_rows_from_receipt(resumed_mapping)
            if (
                not _mapping_rows_match_plan(prepared, rows)
                or
                _mapping_digest(rows) != resumed_mapping.get("mapping_digest")
                or reconcile_mapping is None
                or not reconcile_mapping(rows)
            ):
                raise ValueError("historical_apply_mapping_reconciliation_failed")
            mapping = MappingSyncResult(dry_run=False, rows=rows)
        else:
            mapping = synchronizer.sync_rank1_mapping(
                symbol="jm",
                start_day=days[0],
                end_day=days[-1],
                expected_trading_days=days,
                allowed_contracts=prepared.allowed_actual_contracts,
                dry_run=False,
            )
            if not isinstance(mapping, MappingSyncResult) or mapping.dry_run:
                raise ValueError("historical_apply_mapping_result_invalid")
            commit()
            mapping_digest = _mapping_digest(mapping.rows)
            if receipt_store is not None:
                receipt_store.record_mapping(
                    status="passed",
                    row_count=len(mapping.rows),
                    mapping_digest=mapping_digest,
                    rows=tuple(_mapping_row_identity(row) for row in mapping.rows),
                    progress_state_digest=(
                        capture_progress_state_digest()
                        if capture_progress_state_digest is not None
                        else None
                    ),
                )

        actual_contracts = tuple(
            sorted({row.actual_contract for row in mapping.rows})
        )
        datasets = prepared.datasets_for_contracts(actual_contracts)
        results: list[dict[str, Any]] = []
        for dataset in datasets:
            identity = _dataset_identity(dataset)
            recorded = (
                receipt_store.completed_dataset(identity)
                if receipt_store is not None
                else None
            )
            if recorded is not None:
                if (
                    reconcile_completed_dataset is None
                    or not reconcile_completed_dataset(dataset, recorded)
                ):
                    raise ValueError("historical_apply_dataset_reconciliation_failed")
                results.append(
                    {
                        "dataset": identity,
                        "planned_window_count": 0,
                        "published_window_count": 0,
                        "gap_window_count": 0,
                        "resumed_from_receipt": True,
                    }
                )
                continue
            windows = _dataset_write_windows(prepared, dataset, mapping.rows)
            synced_results = tuple(
                synchronizer.sync(
                    dataset=dataset,
                    start=window_start,
                    end=window_end,
                    dry_run=False,
                )
                for window_start, window_end in windows
            )
            if any(
                not isinstance(synced, SyncResult) or synced.dry_run
                for synced in synced_results
            ):
                raise ValueError("historical_apply_sync_result_invalid")
            synced = SyncResult(
                dry_run=False,
                planned_windows=tuple(
                    item
                    for result in synced_results
                    for item in result.planned_windows
                ),
                published_windows=tuple(
                    item
                    for result in synced_results
                    for item in result.published_windows
                ),
                gap_windows=tuple(
                    item
                    for result in synced_results
                    for item in result.gap_windows
                ),
            )
            commit()
            item = {
                "dataset": identity,
                "planned_window_count": len(synced.planned_windows),
                "published_window_count": len(synced.published_windows),
                "gap_window_count": len(synced.gap_windows),
                "resumed_from_receipt": False,
            }
            results.append(item)
            if receipt_store is not None:
                receipt_store.record_dataset(
                    dataset=identity,
                    status="blocked" if synced.gap_windows else "passed",
                    planned_windows=tuple(
                        (start.isoformat(), end.isoformat())
                        for start, end in synced.planned_windows
                    ),
                    published_window_count=len(synced.published_windows),
                    gap_window_count=len(synced.gap_windows),
                    partition_evidence=(
                        tuple(capture_partition_evidence(dataset))
                        if capture_partition_evidence is not None
                        else ()
                    ),
                    progress_state_digest=(
                        capture_progress_state_digest()
                        if capture_progress_state_digest is not None
                        else None
                    ),
                )
    except Exception:
        rollback()
        raise

    gap_count = sum(item["gap_window_count"] > 0 for item in results)
    return {
        "schema_version": 1,
        "command": "data.migrate.apply",
        "status": "blocked" if gap_count else "passed",
        "readonly": False,
        "effects": {
            "calls_rqdata": True,
            "writes_postgresql": True,
            "writes_parquet": True,
            "writes_legacy_market_data_assets": False,
        },
        "task_head": prepared.task_head,
        "plan_digest": prepared.plan_digest,
        "mapping_row_count": len(mapping.rows),
        "dataset_count": len(results),
        "gap_dataset_count": gap_count,
        "datasets": results,
    }


def filter_actual_dominant_sessions(
    dataset: DatasetKey,
    sessions: Sequence[TradingSessionCoverage],
    *,
    actual_contract_for_day: Callable[[date], str],
) -> tuple[TradingSessionCoverage, ...]:
    normalized = tuple(sessions)
    if dataset.dataset_kind is DatasetKind.CONTINUOUS:
        return normalized
    if dataset.dataset_kind is not DatasetKind.ACTUAL_DOMINANT:
        raise ValueError("historical_apply_dataset_kind_invalid")
    return tuple(
        session
        for session in normalized
        if actual_contract_for_day(session.trading_day).strip().upper()
        == dataset.contract_or_series
    )


def _trading_days(
    values: Sequence[date],
    prepared: PreparedHistoricalApply,
) -> tuple[date, ...]:
    days = tuple(sorted(set(values)))
    if (
        not days
        or any(not isinstance(item, date) or isinstance(item, datetime) for item in days)
        or days[0] < prepared.start.date()
        or days[-1] > prepared.end.date()
    ):
        raise ValueError("historical_apply_trading_days_invalid")
    return days


def _aware_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.astimezone(UTC)


def _dataset_identity(dataset: DatasetKey) -> dict[str, str]:
    return {
        "provider": dataset.provider,
        "dataset_kind": dataset.dataset_kind.value,
        "symbol": dataset.symbol,
        "contract_or_series": dataset.contract_or_series,
        "frequency": dataset.frequency.value,
        "adjustment": dataset.adjustment,
        "schema_version": dataset.schema_version,
    }


def _mapping_digest(rows: Sequence[object]) -> str:
    import hashlib
    import json

    payload = [
        {
            "symbol": row.symbol,
            "trading_day": row.trading_day.isoformat(),
            "actual_contract": row.actual_contract,
            "rank": row.rank,
            "data_version": row.data_version,
        }
        for row in rows
    ]
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _mapping_row_identity(row: MainMapRow) -> dict[str, Any]:
    return {
        "symbol": row.symbol,
        "trading_day": row.trading_day.isoformat(),
        "actual_contract": row.actual_contract,
        "rank": row.rank,
        "data_version": row.data_version,
    }


def _mapping_rows_from_receipt(value: Mapping[str, Any]) -> tuple[MainMapRow, ...]:
    raw_rows = value.get("rows")
    if not isinstance(raw_rows, list):
        raise ValueError("historical_apply_mapping_receipt_invalid")
    try:
        rows = tuple(
            MainMapRow(
                symbol=item["symbol"],
                trading_day=date.fromisoformat(item["trading_day"]),
                actual_contract=item["actual_contract"],
                rank=item["rank"],
                data_version=item["data_version"],
            )
            for item in raw_rows
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("historical_apply_mapping_receipt_invalid") from exc
    return rows


def _mapping_rows_match_plan(
    prepared: PreparedHistoricalApply,
    rows: Sequence[MainMapRow],
) -> bool:
    return (
        tuple(sorted({row.trading_day for row in rows}))
        == prepared.mapping_trading_days
        and all(
            row.symbol == "jm"
            and row.rank == 1
            and row.actual_contract in prepared.allowed_actual_contracts
            for row in rows
        )
    )


def _dataset_write_windows(
    prepared: PreparedHistoricalApply,
    dataset: DatasetKey,
    mapping_rows: Sequence[object],
) -> tuple[tuple[datetime, datetime], ...]:
    if dataset.dataset_kind is DatasetKind.CONTINUOUS:
        return ((prepared.start, prepared.end),)
    mapping = {
        row.trading_day: row.actual_contract
        for row in mapping_rows
    }
    windows = tuple(
        (window_start, window_end)
        for trading_day, window_start, window_end in prepared.mapping_session_windows
        if mapping.get(trading_day) == dataset.contract_or_series
    )
    if not windows:
        raise ValueError("historical_apply_actual_mapping_segment_missing")
    return windows
