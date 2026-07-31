from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Iterable, Mapping, Sequence

import pyarrow.parquet as pq
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.data_core.catalog import CatalogError, HistoricalCatalog
from app.data_core.contracts import BarFrequency, DatasetKey, DatasetKind
from app.data_core.historical_sessions import jm_provider_sessions
from app.data_core.historical_sync import plan_missing_windows
from app.models.data_center import MarketDataFile


_DIRECT_FREQUENCIES = frozenset({"1m", "1d", "1w"})
_BAR_FREQUENCIES = frozenset({"1m", "5m", "15m", "30m", "60m", "1d", "1w"})
_IDENTITY_FIELDS = (
    "provider",
    "dataset_kind",
    "symbol",
    "contract_or_series",
    "frequency",
    "adjustment",
    "schema_version",
)
_VALUE_FIELDS = (
    "trading_day",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "turnover",
    "open_interest",
)
_COMPARE_FIELDS = _IDENTITY_FIELDS + _VALUE_FIELDS
_ACTUAL_JM_CONTRACT = re.compile(r"JM\d{4}\Z")


@dataclass(frozen=True, slots=True)
class LegacyAssetInventory:
    market_data_file_id: int
    provider: str
    dataset_kind: str
    symbol: str
    contract_or_series: str
    period: str
    coverage_start: str
    coverage_end: str
    row_count: int
    data_version: str
    data_role: str
    quality_status: str
    file_path: str
    physical_exists: bool
    checksum_declared: str | None
    checksum_actual: str
    checksum_status: str
    source_intervals: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class HistoricalShadowQuery:
    dataset_kind: str
    contract_or_series: str | None
    frequency: str
    start: str
    end: str


@dataclass(frozen=True, slots=True)
class ShadowException:
    bar_end: str
    reason: str
    allowed_fields: tuple[str, ...] = ()
    allow_missing: bool = False

    def __post_init__(self) -> None:
        normalized_end = _bar_key(self.bar_end)
        reason = str(self.reason).strip()
        fields = tuple(sorted(set(self.allowed_fields)))
        if not reason or any(field not in _VALUE_FIELDS for field in fields):
            raise ValueError("shadow exception invalid")
        if type(self.allow_missing) is not bool or (not fields and not self.allow_missing):
            raise ValueError("shadow exception invalid")
        object.__setattr__(self, "bar_end", normalized_end)
        object.__setattr__(self, "reason", reason)
        object.__setattr__(self, "allowed_fields", fields)


def build_jm_shadow_query_set(
    *,
    start: datetime,
    end: datetime,
) -> tuple[HistoricalShadowQuery, ...]:
    window_start = _aware_utc(start, "start")
    window_end = _aware_utc(end, "end")
    if window_start >= window_end:
        raise ValueError("shadow window must be increasing")
    matrix = {
        "continuous": ("1m", "5m", "15m", "30m", "60m", "1d", "1w"),
        "actual_dominant": ("1m", "5m", "15m", "30m", "60m", "1d"),
    }
    return tuple(
        HistoricalShadowQuery(
            dataset_kind=dataset_kind,
            contract_or_series=("JM.MAIN" if dataset_kind == "continuous" else None),
            frequency=frequency,
            start=window_start.isoformat(),
            end=window_end.isoformat(),
        )
        for dataset_kind, frequencies in matrix.items()
        for frequency in frequencies
    )


def run_historical_shadow_query_set(
    queries: Sequence[HistoricalShadowQuery],
    *,
    legacy_reader: Any,
    canonical_reader: Any,
    allowed_exceptions: Mapping[str, Sequence[ShadowException]] | None = None,
    expected_actual_contract_by_day: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    if not callable(legacy_reader) or not callable(canonical_reader):
        raise ValueError("shadow readers must be callable")
    query_tuple = tuple(queries)
    if not query_tuple:
        raise ValueError("shadow query set required")
    expected = build_jm_shadow_query_set(
        start=_aware_utc(datetime.fromisoformat(query_tuple[0].start), "start"),
        end=_aware_utc(datetime.fromisoformat(query_tuple[0].end), "end"),
    )
    if query_tuple != expected:
        raise ValueError("shadow query set must match frozen JM matrix")
    exceptions = allowed_exceptions or {}
    query_set_digest = _canonical_digest(
        {"queries": [asdict(item) for item in query_tuple]}
    )
    mapping_evidence = dict(expected_actual_contract_by_day or {})
    mapping_evidence_digest = _canonical_digest({"mapping": mapping_evidence})
    results: list[dict[str, Any]] = []
    for query in query_tuple:
        if not isinstance(query, HistoricalShadowQuery):
            raise ValueError("shadow query invalid")
        query_id = f"{query.dataset_kind}:{query.frequency}"
        compared = compare_shadow_bars(
            legacy_reader(query),
            canonical_reader(query),
            allowed_exceptions=tuple(exceptions.get(query_id, ())),
            expected_identity={
                "provider": "rqdata",
                "dataset_kind": query.dataset_kind,
                "symbol": "jm",
                "contract_or_series": query.contract_or_series,
                "frequency": query.frequency,
                "adjustment": "none",
                "schema_version": "canonical-bar-v1",
            },
            expected_actual_contract_by_day=(
                mapping_evidence
                if query.dataset_kind == "actual_dominant"
                else None
            ),
        )
        results.append({"query_id": query_id, "query": asdict(query), **compared})
    blocked = [item for item in results if item["status"] == "blocked"]
    receipt = {
        "schema_version": 1,
        "status": "blocked" if blocked else "passed",
        "query_count": len(results),
        "blocked_query_count": len(blocked),
        "query_set_digest": query_set_digest,
        "mapping_evidence_digest": mapping_evidence_digest,
        "results": results,
    }
    return {**receipt, "receipt_digest": _canonical_digest(receipt)}


def inventory_jm_legacy_assets(
    session: Session,
    *,
    project_root: Path,
) -> tuple[LegacyAssetInventory, ...]:
    if not isinstance(project_root, Path) or not project_root.is_absolute():
        raise ValueError("project_root must be absolute")
    rows = list(
        session.scalars(
            select(MarketDataFile)
            .where(
                func.lower(MarketDataFile.instrument_symbol) == "jm",
                func.lower(MarketDataFile.period).in_(_BAR_FREQUENCIES),
            )
            .order_by(MarketDataFile.period.asc(), MarketDataFile.id.asc())
        )
    )
    inventory: list[LegacyAssetInventory] = []
    for row in rows:
        path = Path(row.file_path)
        if not path.is_absolute():
            path = project_root / path
        path = path.resolve(strict=False)
        exists = path.is_file()
        actual_checksum = _sha256(path) if exists else ""
        declared_checksum = _clean_optional(row.checksum)
        if not exists:
            checksum_status = "missing"
        elif declared_checksum and declared_checksum != actual_checksum:
            checksum_status = "mismatch"
        else:
            checksum_status = "matched" if declared_checksum else "computed"
        inventory.append(
            LegacyAssetInventory(
                market_data_file_id=int(row.id),
                provider=str(row.provider or "").strip().lower(),
                dataset_kind=_dataset_kind(row.data_type, row.contract_code),
                symbol="jm",
                contract_or_series=str(row.contract_code or "").strip().upper(),
                period=str(row.period or "").strip().lower(),
                coverage_start=_utc_iso(row.start_time),
                coverage_end=_utc_iso(row.end_time),
                row_count=int(row.row_count or 0),
                data_version=str(row.data_version or ""),
                data_role=str(row.data_role or ""),
                quality_status=str(row.quality_status or ""),
                file_path=str(path),
                physical_exists=exists,
                checksum_declared=declared_checksum,
                checksum_actual=actual_checksum,
                checksum_status=checksum_status,
                source_intervals=_source_intervals(path) if exists else (),
            )
        )
    return tuple(inventory)


def build_jm_migration_plan(
    inventory: Sequence[LegacyAssetInventory],
) -> dict[str, Any]:
    eligible: list[LegacyAssetInventory] = []
    excluded: list[dict[str, object]] = []
    for item in inventory:
        reason = _exclusion_reason(item)
        if reason is None:
            eligible.append(item)
        else:
            excluded.append(
                {
                    "market_data_file_id": item.market_data_file_id,
                    "reason": reason,
                }
            )
    facts = {
        "schema_version": 1,
        "task": "GY-DATA-CORE-V2-04",
        "symbol": "jm",
        "eligible_assets": [_plan_asset(item) for item in eligible],
        "excluded": excluded,
        "target": {
            "provider": "rqdata",
            "schema_version": "canonical-bar-v1",
            "direct_frequencies": ["1m", "1d", "1w"],
            "direct_frequency_matrix": {
                "continuous": ["1m", "1d", "1w"],
                "actual_dominant": ["1m", "1d"],
            },
            "derived_frequencies": ["5m", "15m", "30m", "60m"],
        },
        "writes": {
            "rqdata_calls": False,
            "postgresql": False,
            "parquet": False,
        },
        "rollback": {
            "deletes_legacy": False,
            "physical_delete": False,
            "strategy": "keep_legacy_readonly_and_disable_canonical_consumer",
        },
    }
    return {
        **facts,
        "eligible_market_data_file_ids": [
            item.market_data_file_id for item in eligible
        ],
        "plan_digest": _canonical_digest(facts),
    }


def build_jm_apply_bound_facts(
    inventory: Sequence[LegacyAssetInventory],
    *,
    plan: Mapping[str, Any],
    task_head: str,
    canonical_root: Path,
    staging_root: Path,
    postgresql_target: Mapping[str, Any],
    start: datetime,
    end: datetime,
    source_checkout: Path,
    current_state: Mapping[str, Any],
    receipt_path: Path,
) -> dict[str, Any]:
    if not isinstance(canonical_root, Path) or not canonical_root.is_absolute():
        raise ValueError("canonical_root must be absolute")
    if not isinstance(staging_root, Path) or not staging_root.is_absolute():
        raise ValueError("staging_root must be absolute")
    if not isinstance(source_checkout, Path) or not source_checkout.is_absolute():
        raise ValueError("source_checkout must be absolute")
    if not isinstance(receipt_path, Path) or not receipt_path.is_absolute():
        raise ValueError("receipt_path must be absolute")
    window_start = _aware_utc(start, "start")
    window_end = _aware_utc(end, "end")
    if window_start >= window_end:
        raise ValueError("migration window must be increasing")
    if not isinstance(plan, Mapping) or not isinstance(
        plan.get("plan_digest"),
        str,
    ):
        raise ValueError("migration plan digest required")
    actual_contracts = {
        item.contract_or_series
        for item in inventory
        if _ACTUAL_JM_CONTRACT.fullmatch(item.contract_or_series)
    }
    has_continuous = any(
        item.dataset_kind == "continuous" for item in inventory
    )
    if not actual_contracts or not has_continuous:
        raise ValueError("jm migration target identities incomplete")
    contracts = sorted({"JM.MAIN", *actual_contracts})
    trading_days = list(current_state.get("trading_days", ()))
    if not trading_days:
        raise ValueError("jm mapping acquisition trading days required")
    return {
        "task_head": task_head,
        "source_checkout": str(source_checkout.resolve(strict=False)),
        "migration_revisions": ["20260730_0026", "20260730_0027"],
        "scope": {
            "symbol": "jm",
            "provider": "rqdata",
            "schema_version": "canonical-bar-v1",
            "dataset_kinds": ["continuous", "actual_dominant"],
            "direct_frequencies": ["1m", "1d", "1w"],
            "direct_frequency_matrix": {
                "continuous": ["1m", "1d", "1w"],
                "actual_dominant": ["1m", "1d"],
            },
            "window": {
                "start": window_start.isoformat(),
                "end": window_end.isoformat(),
            },
            "contract_or_series": contracts,
        },
        "plan_digest": plan["plan_digest"],
        "mapping_write_plan": {
            "provider": "rqdata",
            "symbol": "jm",
            "rank": 1,
            "start_day": trading_days[0],
            "end_day": trading_days[-1],
            "trading_days": trading_days,
            "allowed_contracts": contracts[1:],
        },
        "current_state": dict(current_state),
        "write_set": {
            "canonical_root": str(canonical_root),
            "staging_root": str(staging_root),
            "postgresql_target": dict(postgresql_target),
            "postgresql_tables": [
                "market_datasets",
                "market_partitions",
                "data_gaps",
                "main_contract_map",
            ],
            "writes_legacy_market_data_assets": False,
            "partial_apply_receipt": str(receipt_path),
        },
        "rollback": {
            "deletes_physical_data": False,
            "strategy": "keep_legacy_readonly_and_disable_canonical_consumer",
        },
    }


def build_jm_current_state(
    session: Session,
    *,
    start: datetime,
    end: datetime,
) -> dict[str, Any]:
    window_start = _aware_utc(start, "start")
    window_end = _aware_utc(end, "end")
    catalog = HistoricalCatalog(session)
    sessions = jm_provider_sessions_for_state(session, window_start, window_end)
    trading_days = sorted({item.trading_day for item in sessions})
    mappings: dict[object, str] = {}
    missing_mapping_days: list[str] = []
    mapping_rows: list[dict[str, str]] = []
    for trading_day in trading_days:
        try:
            mapping = catalog.get_main_contract_mapping(
                instrument_symbol="jm",
                trade_date=trading_day,
            )
        except CatalogError:
            missing_mapping_days.append(trading_day.isoformat())
            continue
        mappings[trading_day] = mapping.actual_contract
        mapping_rows.append(
            {
                "symbol": "jm",
                "trading_day": trading_day.isoformat(),
                "actual_contract": mapping.actual_contract,
                "rank": 1,
                "data_version": mapping.data_version,
            }
        )
    datasets = [
        DatasetKey(
            provider="rqdata",
            dataset_kind=DatasetKind.CONTINUOUS,
            symbol="jm",
            contract_or_series="JM.MAIN",
            frequency=frequency,
            adjustment="none",
            schema_version="canonical-bar-v1",
        )
        for frequency in (BarFrequency.M1, BarFrequency.D1, BarFrequency.W1)
    ]
    datasets.extend(
        DatasetKey(
            provider="rqdata",
            dataset_kind=DatasetKind.ACTUAL_DOMINANT,
            symbol="jm",
            contract_or_series=contract,
            frequency=frequency,
            adjustment="none",
            schema_version="canonical-bar-v1",
        )
        for contract in sorted(set(mappings.values()))
        for frequency in (BarFrequency.M1, BarFrequency.D1)
    )
    dataset_plans: list[dict[str, Any]] = []
    catalog_facts: list[dict[str, Any]] = []
    for dataset in datasets:
        partitions = tuple(catalog.list_partitions(dataset))
        gaps = tuple(catalog.list_gaps(dataset))
        valid_windows = [(window_start, window_end)]
        if dataset.dataset_kind is DatasetKind.ACTUAL_DOMINANT:
            valid_windows = [
                (item.start, item.end)
                for item in jm_provider_sessions(
                    session,
                    dataset,
                    window_start,
                    window_end,
                )
                if mappings.get(item.trading_day) == dataset.contract_or_series
            ]
        missing_windows = [
            missing
            for valid_start, valid_end in valid_windows
            for missing in plan_missing_windows(
                dataset=dataset,
                start=valid_start,
                end=valid_end,
                covered_windows=tuple(
                    (item.coverage_start, item.coverage_end)
                    for item in partitions
                ),
            )
        ]
        identity = _dataset_identity(dataset)
        dataset_plans.append(
            {
                "dataset": identity,
                "mapping_valid_windows": [
                    [item[0].isoformat(), item[1].isoformat()]
                    for item in valid_windows
                ],
                "missing_windows": [
                    [item[0].isoformat(), item[1].isoformat()]
                    for item in missing_windows
                ],
            }
        )
        catalog_facts.append(
            {
                "dataset": identity,
                "partitions": [
                    {
                        "coverage_start": item.coverage_start.isoformat(),
                        "coverage_end": item.coverage_end.isoformat(),
                        "manifest_digest": item.manifest_digest,
                        "checksum": item.checksum,
                    }
                    for item in partitions
                ],
                "gaps": [
                    {
                        "gap_start": item.gap_start.isoformat(),
                        "gap_end": item.gap_end.isoformat(),
                        "reason_code": item.reason_code,
                    }
                    for item in gaps
                ],
            }
        )
    session_facts = [
        {
            "trading_day": item.trading_day.isoformat(),
            "start": item.start.isoformat(),
            "end": item.end.isoformat(),
        }
        for item in sessions
    ]
    facts = {
        "catalog_digest": _canonical_digest({"items": catalog_facts}),
        "catalog_items": catalog_facts,
        "mapping_digest": _canonical_digest({"rows": mapping_rows}),
        "mapping_rows": mapping_rows,
        "calendar_digest": _canonical_digest(
            {"trading_days": [item.isoformat() for item in trading_days]}
        ),
        "session_digest": _canonical_digest({"sessions": session_facts}),
        "dataset_write_plan_digest": _canonical_digest({"plans": dataset_plans}),
        "mapping_complete": not missing_mapping_days and bool(trading_days),
        "missing_mapping_days": missing_mapping_days,
        "trading_days": [item.isoformat() for item in trading_days],
        "session_windows": session_facts,
        "dataset_write_plan": dataset_plans,
    }
    return {**facts, "state_digest": _canonical_digest(facts)}


def jm_provider_sessions_for_state(
    session: Session,
    start: datetime,
    end: datetime,
) -> tuple[Any, ...]:
    from app.services.canonical_market_data import jm_sessions

    return tuple(jm_sessions(session, symbol="jm", start=start, end=end))


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


def compare_shadow_bars(
    legacy_bars: Iterable[Mapping[str, Any]],
    canonical_bars: Iterable[Mapping[str, Any]],
    *,
    allowed_exceptions: Sequence[ShadowException] = (),
    expected_identity: Mapping[str, Any] | None = None,
    expected_actual_contract_by_day: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    legacy = _bars_by_key(legacy_bars)
    canonical = _bars_by_key(canonical_bars)
    exceptions = {item.bar_end: item for item in allowed_exceptions}
    if len(exceptions) != len(tuple(allowed_exceptions)):
        raise ValueError("shadow exception duplicate")
    differences: list[dict[str, object]] = []
    explained: list[str] = []
    for key in sorted(set(legacy) | set(canonical)):
        left = legacy.get(key)
        right = canonical.get(key)
        if expected_identity is not None:
            invalid_sides = [
                side
                for side, row in (("legacy", left), ("canonical", right))
                if row is not None
                and not _shadow_row_matches_query_identity(
                    row,
                    expected_identity,
                    expected_actual_contract_by_day=expected_actual_contract_by_day,
                )
            ]
            if invalid_sides:
                differences.append(
                    {
                        "bar_end": key,
                        "reason": "query_identity_mismatch",
                        "fields": invalid_sides,
                    }
                )
                continue
        if left is None or right is None:
            exception = exceptions.get(key)
            if exception is not None and exception.allow_missing:
                explained.append(key)
                continue
            differences.append(
                {
                    "bar_end": key,
                    "reason": "missing_row",
                    "fields": [],
                }
            )
            continue
        mismatched = [
            field
            for field in _COMPARE_FIELDS
            if _comparison_value(left.get(field))
            != _comparison_value(right.get(field))
        ]
        if mismatched:
            exception = exceptions.get(key)
            if exception is not None and set(mismatched) <= set(exception.allowed_fields):
                explained.append(key)
                continue
            differences.append(
                {
                    "bar_end": key,
                    "reason": "value_mismatch",
                    "fields": mismatched,
                }
            )
    status = "blocked" if differences else "passed"
    if not differences and explained:
        status = "passed_with_declared_boundaries"
    return {
        "status": status,
        "legacy_row_count": len(legacy),
        "canonical_row_count": len(canonical),
        "differences": differences,
        "explained_boundary_keys": explained,
    }


def _shadow_row_matches_query_identity(
    row: Mapping[str, Any],
    expected: Mapping[str, Any],
    *,
    expected_actual_contract_by_day: Mapping[str, str] | None,
) -> bool:
    for field in _IDENTITY_FIELDS:
        if field == "contract_or_series" and expected.get(field) is None:
            continue
        if _comparison_value(row.get(field)) != _comparison_value(expected.get(field)):
            return False
    if expected.get("contract_or_series") is not None:
        return True
    if expected.get("dataset_kind") != "actual_dominant":
        return False
    symbol = str(expected.get("symbol", "")).upper()
    contract = str(row.get("contract_or_series", "")).upper()
    if re.fullmatch(rf"{re.escape(symbol)}\d{{3,4}}", contract) is None:
        return False
    if expected_actual_contract_by_day is None:
        return True
    trading_day = str(row.get("trading_day", ""))
    return expected_actual_contract_by_day.get(trading_day) == contract


def _exclusion_reason(item: LegacyAssetInventory) -> str | None:
    if not item.physical_exists:
        return "physical_file_missing"
    if item.checksum_status == "mismatch":
        return "checksum_mismatch"
    if item.provider != "rqdata":
        return "provider_not_rqdata"
    if item.data_role != "primary":
        return "data_role_not_primary"
    if item.quality_status != "passed":
        return "quality_not_passed"
    if item.dataset_kind == "actual_dominant" and item.period == "1w":
        return "actual_dominant_weekly_identity_not_supported"
    if item.period not in _DIRECT_FREQUENCIES:
        return "derived_frequency_not_persisted"
    if item.period == "1d" and "1m" in item.source_intervals:
        return "derived_daily_not_rqdata_direct"
    if item.period in {"1d", "1w"} and not item.source_intervals:
        return "direct_provenance_unproven"
    if item.period in _DIRECT_FREQUENCIES and item.source_intervals != (
        item.period,
    ):
        return "source_interval_not_direct"
    if not item.contract_or_series:
        return "contract_identity_missing"
    return None


def _plan_asset(item: LegacyAssetInventory) -> dict[str, Any]:
    return asdict(item)


def _dataset_kind(data_type: object, contract: object) -> str:
    normalized = str(data_type or "").strip().lower()
    if normalized in {"continuous", "actual_dominant"}:
        return normalized
    contract_value = str(contract or "").strip().upper()
    if contract_value.endswith((".MAIN", "88", "888")):
        return "continuous"
    return "actual_dominant"


def _source_intervals(path: Path) -> tuple[str, ...]:
    try:
        schema = pq.read_schema(path)
        if "source_interval" not in schema.names:
            return ()
        values = pq.ParquetFile(path).read(columns=["source_interval"])[
            "source_interval"
        ].to_pylist()
    except (OSError, ValueError):
        return ()
    return tuple(sorted({str(value).strip().lower() for value in values if value}))


def _bars_by_key(
    rows: Iterable[Mapping[str, Any]],
) -> dict[str, Mapping[str, Any]]:
    result: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            raise ValueError("shadow row must be a mapping")
        key = _bar_key(row.get("bar_end") or row.get("datetime") or row.get("time"))
        existing = result.get(key)
        if existing is not None and existing != row:
            raise ValueError("shadow same-key conflict")
        result[key] = row
    return result


def _bar_key(value: object) -> str:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    else:
        raise ValueError("shadow bar_end missing")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("shadow bar_end timezone required")
    return parsed.astimezone(UTC).isoformat()


def _comparison_value(value: object) -> object:
    if value is None:
        return None
    if isinstance(value, (int, float, Decimal)):
        try:
            return Decimal(str(value)).normalize()
        except InvalidOperation:
            return str(value)
    if isinstance(value, str):
        try:
            return Decimal(value).normalize()
        except InvalidOperation:
            return value
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_digest(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _utc_iso(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat()


def _clean_optional(value: object) -> str | None:
    text = str(value or "").strip().lower()
    return text or None


def _aware_utc(value: object, field: str) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise ValueError(f"{field} must be timezone-aware")
    return value.astimezone(UTC)
