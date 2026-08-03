"""Hash-bound orchestration for the one approved JM historical apply.

This module is deliberately split into preparation and execution. Packet and
current-fact verification completes before callers construct RQData or
CanonicalStore dependencies with write side effects.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol, Sequence

from app.data_core.contracts import BarFrequency, DatasetKey, DatasetKind
from app.data_core.historical_apply_gate import (
    VerifiedApplyProgress,
    verify_apply_approval_packet,
)
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
    verified_mapping_rows: tuple[dict[str, Any], ...]
    verified_completed_datasets: tuple[dict[str, Any], ...]
    verified_progress_state_digest: str
    execution_runs_by_dataset: tuple[
        tuple[str, tuple[tuple[datetime, datetime], ...]], ...
    ] = ()
    replacement_dataset_tokens: tuple[str, ...] = ()

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
    verified_progress: VerifiedApplyProgress | None = None,
) -> PreparedHistoricalApply:
    verify_apply_approval_packet(
        packet,
        approval_hash=approval_hash,
        current_facts=current_facts,
        progress_receipt=progress_receipt,
        verified_progress=verified_progress,
    )
    facts = packet["bound_facts"]
    scope = facts["scope"]
    write_set = facts["write_set"]
    mapping_plan = facts["mapping_write_plan"]
    state = facts["current_state"]
    execution_state = current_facts["current_state"]
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
        verified_mapping_rows=(
            verified_progress.mapping_rows if verified_progress is not None else ()
        ),
        verified_completed_datasets=(
            verified_progress.completed_datasets
            if verified_progress is not None
            else ()
        ),
        verified_progress_state_digest=(
            verified_progress.current_state_digest
            if verified_progress is not None
            else state["state_digest"]
        ),
        execution_runs_by_dataset=tuple(
            (
                _dataset_identity_token(item["dataset"]),
                tuple(
                    (_aware_utc(window[0]), _aware_utc(window[1]))
                    for window in item["execution_runs"]
                ),
            )
            for item in execution_state["dataset_write_plan"]
        ),
        replacement_dataset_tokens=tuple(
            _dataset_identity_token(item["dataset"])
            for item in execution_state["dataset_write_plan"]
            if item["replacement_required"] is True
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
    days = _trading_days(expected_trading_days)
    if days != prepared.mapping_trading_days:
        raise ValueError("historical_apply_mapping_plan_days_changed")
    try:
        existing_rows = (
            _mapping_rows_from_receipt(
                {"rows": list(prepared.verified_mapping_rows)}
            )
            if prepared.verified_mapping_rows
            else ()
        )
        if existing_rows:
            if (
                not _mapping_rows_within_plan(prepared, existing_rows)
                or reconcile_mapping is None
                or not reconcile_mapping(existing_rows)
            ):
                raise ValueError("historical_apply_mapping_reconciliation_failed")
        existing_days = {row.trading_day for row in existing_rows}
        missing_days = tuple(day for day in days if day not in existing_days)
        progress_state_digest = prepared.verified_progress_state_digest
        if missing_days:
            fetched_rows: list[MainMapRow] = []
            for missing_run in _missing_trading_day_runs(days, existing_days):
                fetched = synchronizer.sync_rank1_mapping(
                    symbol="jm",
                    start_day=missing_run[0],
                    end_day=missing_run[-1],
                    expected_trading_days=missing_run,
                    allowed_contracts=prepared.allowed_actual_contracts,
                    dry_run=False,
                )
                if (
                    not isinstance(fetched, MappingSyncResult)
                    or fetched.dry_run
                    or not _mapping_rows_match_days(
                        prepared,
                        fetched.rows,
                        missing_run,
                    )
                ):
                    raise ValueError("historical_apply_mapping_result_invalid")
                fetched_rows.extend(fetched.rows)
            rows = tuple(
                sorted(
                    (*existing_rows, *fetched_rows),
                    key=lambda row: row.trading_day,
                )
            )
            if not _mapping_rows_match_plan(prepared, rows):
                raise ValueError("historical_apply_mapping_result_invalid")
            mapping = MappingSyncResult(dry_run=False, rows=rows)
            commit()
            progress_state_digest = (
                capture_progress_state_digest()
                if capture_progress_state_digest is not None
                else None
            )
        else:
            if not _mapping_rows_match_plan(prepared, existing_rows):
                raise ValueError("historical_apply_mapping_reconciliation_failed")
            mapping = MappingSyncResult(dry_run=False, rows=existing_rows)
        if receipt_store is not None:
            receipt_store.record_mapping(
                status="passed",
                row_count=len(mapping.rows),
                mapping_digest=_mapping_digest(mapping.rows),
                rows=tuple(_mapping_row_identity(row) for row in mapping.rows),
                progress_state_digest=progress_state_digest,
            )

        actual_contracts = tuple(
            sorted({row.actual_contract for row in mapping.rows})
        )
        datasets = prepared.datasets_for_contracts(actual_contracts)
        results: list[dict[str, Any]] = []
        completed_by_identity = {
            _dataset_identity_token(item["dataset"]): item
            for item in prepared.verified_completed_datasets
        }
        replacement_datasets = set(prepared.replacement_dataset_tokens)
        for dataset in datasets:
            identity = _dataset_identity(dataset)
            identity_token = _dataset_identity_token(identity)
            recorded = completed_by_identity.get(identity_token)
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
                if receipt_store is not None:
                    evidence = tuple(recorded["partition_evidence"])
                    receipt_store.record_dataset(
                        dataset=identity,
                        status="passed",
                        planned_windows=(),
                        published_window_count=len(evidence),
                        gap_window_count=0,
                        partition_evidence=evidence,
                        progress_state_digest=prepared.verified_progress_state_digest,
                    )
                continue
            windows = _dataset_write_windows(prepared, dataset, mapping.rows)
            synced_results = tuple(
                synchronizer.sync(
                    dataset=dataset,
                    start=window_start,
                    end=window_end,
                    dry_run=False,
                    replace_existing=identity_token in replacement_datasets,
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
    receipt_summary: dict[str, Any] | None = None
    if receipt_store is not None and not gap_count:
        if capture_progress_state_digest is None:
            raise ValueError("historical_apply_final_state_digest_required")
        final_state_digest = capture_progress_state_digest()
        receipt_store.finalize_passed(
            expected_mapping_row_count=len(mapping.rows),
            expected_mapping_digest=_mapping_digest(mapping.rows),
            expected_datasets=tuple(_dataset_identity(item) for item in datasets),
            progress_state_digest=final_state_digest,
        )
        snapshot = receipt_store.snapshot()
        receipt_summary = {
            "status": snapshot["status"],
            "receipt_digest": snapshot.get("receipt_digest"),
            "completed_dataset_count": len(snapshot.get("datasets", {})),
            "remaining_dataset_count": 0,
        }
    response = {
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
    if receipt_summary is not None:
        response["receipt"] = receipt_summary
    return response


def filter_actual_dominant_sessions(
    dataset: DatasetKey,
    sessions: Sequence[TradingSessionCoverage],
    *,
    actual_contract_for_day: Callable[[date], str],
    first_approved_trading_day: date | None = None,
) -> tuple[TradingSessionCoverage, ...]:
    normalized = tuple(sessions)
    if dataset.dataset_kind is DatasetKind.CONTINUOUS:
        if (
            dataset.frequency is BarFrequency.W1
            and first_approved_trading_day is not None
            and first_approved_trading_day.weekday() > 0
        ):
            # RQData needs the listing-week day as its query anchor even
            # though it does not emit a direct bar for that partial week.
            initial_week = first_approved_trading_day.isocalendar()[:2]
            return tuple(
                replace(session, expected_bar_ends=())
                if session.trading_day.isocalendar()[:2] == initial_week
                else session
                for session in normalized
            )
        return normalized
    if dataset.dataset_kind is not DatasetKind.ACTUAL_DOMINANT:
        raise ValueError("historical_apply_dataset_kind_invalid")
    return tuple(
        session
        for session in normalized
        if actual_contract_for_day(session.trading_day).strip().upper()
        == dataset.contract_or_series
    )


def _trading_days(values: Sequence[date]) -> tuple[date, ...]:
    days = tuple(sorted(set(values)))
    if (
        not days
        or any(not isinstance(item, date) or isinstance(item, datetime) for item in days)
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
    return _mapping_rows_match_days(
        prepared,
        rows,
        prepared.mapping_trading_days,
    )


def _missing_trading_day_runs(
    approved_days: Sequence[date],
    existing_days: set[date],
) -> tuple[tuple[date, ...], ...]:
    """Split missing days when a verified existing approved day separates them."""
    runs: list[tuple[date, ...]] = []
    current: list[date] = []
    for trading_day in approved_days:
        if trading_day in existing_days:
            if current:
                runs.append(tuple(current))
                current = []
            continue
        current.append(trading_day)
    if current:
        runs.append(tuple(current))
    return tuple(runs)


def _mapping_rows_within_plan(
    prepared: PreparedHistoricalApply,
    rows: Sequence[MainMapRow],
) -> bool:
    row_days = tuple(row.trading_day for row in rows)
    return (
        len(row_days) == len(set(row_days))
        and set(row_days) <= set(prepared.mapping_trading_days)
        and _mapping_rows_have_approved_identity(prepared, rows)
    )


def _mapping_rows_match_days(
    prepared: PreparedHistoricalApply,
    rows: Sequence[MainMapRow],
    expected_days: Sequence[date],
) -> bool:
    row_days = tuple(row.trading_day for row in rows)
    return (
        len(row_days) == len(set(row_days))
        and tuple(sorted(row_days)) == tuple(expected_days)
        and _mapping_rows_have_approved_identity(prepared, rows)
    )


def _mapping_rows_have_approved_identity(
    prepared: PreparedHistoricalApply,
    rows: Sequence[MainMapRow],
) -> bool:
    return all(
        row.symbol == "jm"
        and row.rank == 1
        and row.actual_contract in prepared.allowed_actual_contracts
        for row in rows
    )


def _dataset_identity_token(dataset: Mapping[str, Any]) -> str:
    import json

    return json.dumps(dict(dataset), sort_keys=True, separators=(",", ":"))


def _dataset_write_windows(
    prepared: PreparedHistoricalApply,
    dataset: DatasetKey,
    mapping_rows: Sequence[object],
) -> tuple[tuple[datetime, datetime], ...]:
    bound_runs = dict(prepared.execution_runs_by_dataset).get(
        _dataset_identity_token(_dataset_identity(dataset))
    )
    if bound_runs is not None:
        if not bound_runs:
            raise ValueError("historical_apply_execution_runs_missing")
        return bound_runs
    if dataset.dataset_kind is DatasetKind.CONTINUOUS:
        return ((prepared.start, prepared.end),)
    mapping = {
        row.trading_day: row.actual_contract
        for row in mapping_rows
    }
    runs = _actual_contract_day_runs(
        prepared.mapping_trading_days,
        mapping,
        dataset.contract_or_series,
    )
    if dataset.frequency is BarFrequency.D1:
        windows = tuple(
            (
                datetime.combine(run[0], time.min, tzinfo=UTC)
                - timedelta(microseconds=1),
                datetime.combine(run[-1], time.min, tzinfo=UTC),
            )
            for run in runs
        )
        if not windows:
            raise ValueError("historical_apply_actual_mapping_segment_missing")
        return windows
    windows: tuple[tuple[datetime, datetime], ...] = tuple(
        (
            min(item[1] for item in run_windows),
            max(item[2] for item in run_windows),
        )
        for run in runs
        if (
            run_windows := tuple(
                item
                for item in prepared.mapping_session_windows
                if item[0] in set(run)
            )
        )
    )
    if not windows:
        raise ValueError("historical_apply_actual_mapping_segment_missing")
    return windows


def _actual_contract_day_runs(
    approved_days: Sequence[date],
    mapping: Mapping[date, str],
    contract: str,
) -> tuple[tuple[date, ...], ...]:
    runs: list[tuple[date, ...]] = []
    active: list[date] = []
    for trading_day in approved_days:
        if mapping.get(trading_day) == contract:
            active.append(trading_day)
        elif active:
            runs.append(tuple(active))
            active = []
    if active:
        runs.append(tuple(active))
    if not runs:
        raise ValueError("historical_apply_actual_mapping_segment_missing")
    return tuple(runs)
