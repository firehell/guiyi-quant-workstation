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
from app.data_core.historical_sync import MappingSyncResult, SyncResult
from app.data_core.rqdata_adapter import TradingSessionCoverage


_DIRECT_FREQUENCIES = (
    BarFrequency.M1,
    BarFrequency.D1,
    BarFrequency.W1,
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

    def datasets_for_contracts(
        self,
        actual_contracts: Sequence[str],
    ) -> tuple[DatasetKey, ...]:
        normalized = tuple(sorted(set(actual_contracts)))
        if any(item not in self.allowed_actual_contracts for item in normalized):
            raise ValueError("historical_apply_contract_outside_scope")
        identities = ((DatasetKind.CONTINUOUS, "JM.MAIN"),) + tuple(
            (DatasetKind.ACTUAL_DOMINANT, contract)
            for contract in normalized
        )
        return tuple(
            DatasetKey(
                provider="rqdata",
                dataset_kind=dataset_kind,
                symbol="jm",
                contract_or_series=contract,
                frequency=frequency,
                adjustment="none",
                schema_version="canonical-bar-v1",
            )
            for dataset_kind, contract in identities
            for frequency in _DIRECT_FREQUENCIES
        )


def prepare_historical_apply(
    packet: Mapping[str, Any],
    *,
    approval_hash: str,
    current_facts: Mapping[str, Any],
) -> PreparedHistoricalApply:
    verify_apply_approval_packet(
        packet,
        approval_hash=approval_hash,
        current_facts=current_facts,
    )
    facts = packet["bound_facts"]
    scope = facts["scope"]
    write_set = facts["write_set"]
    contracts = tuple(scope["contract_or_series"])
    return PreparedHistoricalApply(
        task_head=str(facts["task_head"]),
        plan_digest=str(facts["plan_digest"]),
        start=_aware_utc(scope["window"]["start"]),
        end=_aware_utc(scope["window"]["end"]),
        allowed_actual_contracts=tuple(contracts[1:]),
        canonical_root=Path(write_set["canonical_root"]),
        staging_root=Path(write_set["staging_root"]),
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
) -> dict[str, Any]:
    days = _trading_days(expected_trading_days, prepared)
    try:
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

        actual_contracts = tuple(
            sorted({row.actual_contract for row in mapping.rows})
        )
        datasets = prepared.datasets_for_contracts(actual_contracts)
        results: list[dict[str, Any]] = []
        for dataset in datasets:
            synced = synchronizer.sync(
                dataset=dataset,
                start=prepared.start,
                end=prepared.end,
                dry_run=False,
            )
            if not isinstance(synced, SyncResult) or synced.dry_run:
                raise ValueError("historical_apply_sync_result_invalid")
            commit()
            results.append(
                {
                    "dataset": _dataset_identity(dataset),
                    "planned_window_count": len(synced.planned_windows),
                    "published_window_count": len(synced.published_windows),
                    "gap_window_count": len(synced.gap_windows),
                }
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
