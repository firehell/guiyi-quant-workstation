"""Read-only JM target Canonical assessment for Task 07 Stage C."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import yaml

from app.data_core.contracts import (
    BAR_FREQUENCY_VALUES,
    BarFrequency,
    BarQuery,
    BarsResult,
    DataCoreError,
    DatasetKey,
    DatasetKind,
)
from app.data_core.catalog import CatalogError, HistoricalCatalog
from app.data_core.historical_reader import CanonicalHistoricalReader
from app.services.canonical_market_data import jm_sessions
from app.services.market_data_service import MarketDataService
from sqlalchemy.orm import Session


_TARGET_ID = "jm_historical_canonical_v1"
_TARGET_FIELDS = {
    "target_id",
    "provider",
    "symbol",
    "continuous_series",
    "dataset_kinds",
    "frequencies",
    "adjustment",
    "schema_version",
    "start_trading_day",
    "end_policy",
    "main_contract",
}
_MAIN_CONTRACT_FIELDS = {"provider", "rank", "rule"}
_FREQUENCY_ORDER = {value: index for index, value in enumerate(BAR_FREQUENCY_VALUES)}


class TargetCanonicalStatus(StrEnum):
    KEEP_CANONICAL = "KEEP_CANONICAL"
    REDOWNLOAD_DIRECT = "REDOWNLOAD_DIRECT"
    REBUILD_AGGREGATE = "REBUILD_AGGREGATE"
    REGISTER_DATA_GAP = "REGISTER_DATA_GAP"


@dataclass(frozen=True, slots=True)
class TargetContract:
    symbol: str
    continuous_series: str
    frequencies: tuple[BarFrequency, ...]
    start_trading_day: date


@dataclass(frozen=True, slots=True)
class MainContractTarget:
    trading_day: date
    actual_contract: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.trading_day, date)
            or not isinstance(self.actual_contract, str)
            or not self.actual_contract.strip().upper().startswith("JM")
            or self.actual_contract.strip().upper().endswith(".MAIN")
        ):
            raise ValueError("TASK07_MAIN_CONTRACT_TARGET_INVALID")
        object.__setattr__(self, "actual_contract", self.actual_contract.strip().upper())


@dataclass(frozen=True, slots=True)
class TargetSession:
    trading_day: date
    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        start = _aware_utc(self.start)
        end = _aware_utc(self.end)
        if not isinstance(self.trading_day, date) or start >= end:
            raise ValueError("TASK07_TARGET_SESSION_INVALID")
        object.__setattr__(self, "start", start)
        object.__setattr__(self, "end", end)


@dataclass(frozen=True, slots=True)
class TargetSpec:
    dataset: DatasetKey
    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.dataset, DatasetKey):
            raise ValueError("TASK07_TARGET_SPEC_INVALID")
        start = _aware_utc(self.start)
        end = _aware_utc(self.end)
        if start >= end:
            raise ValueError("TASK07_TARGET_SPEC_INVALID")
        object.__setattr__(self, "start", start)
        object.__setattr__(self, "end", end)

    def source_1m(self) -> TargetSpec:
        return TargetSpec(
            dataset=DatasetKey(
                provider=self.dataset.provider,
                dataset_kind=self.dataset.dataset_kind,
                symbol=self.dataset.symbol,
                contract_or_series=self.dataset.contract_or_series,
                frequency=BarFrequency.M1,
                adjustment=self.dataset.adjustment,
                schema_version=self.dataset.schema_version,
            ),
            start=self.start,
            end=self.end,
        )


@dataclass(frozen=True, slots=True)
class TargetValidation:
    valid: bool
    reason: str
    explicit_gap: bool = False

    def __post_init__(self) -> None:
        if type(self.valid) is not bool or type(self.explicit_gap) is not bool:
            raise ValueError("TASK07_TARGET_VALIDATION_INVALID")
        if not isinstance(self.reason, str) or not self.reason.strip():
            raise ValueError("TASK07_TARGET_VALIDATION_INVALID")


TargetProbe = Callable[[TargetSpec], TargetValidation]


def run_target_canonical_assessment(
    session: Session,
    *,
    target_config: Path,
    canonical_root: Path,
) -> dict[str, Any]:
    """Assess only configured JM targets; this function has no write path."""

    if not isinstance(session, Session):
        raise TypeError("session must be a Session")
    if not isinstance(canonical_root, Path) or not canonical_root.is_absolute():
        raise ValueError("TASK07_CANONICAL_ROOT_INVALID")
    contract = load_target_contract(target_config)
    catalog = HistoricalCatalog(session)
    mappings = tuple(
        MainContractTarget(item.trading_day, item.actual_contract)
        for item in catalog.list_main_contract_mappings(
            instrument_symbol=contract.symbol,
            start_date=contract.start_trading_day,
        )
    )
    if not mappings:
        raise ValueError("TASK07_MAIN_CONTRACT_MAP_INCOMPLETE")
    sessions = _target_sessions(session, contract=contract, mappings=mappings)
    specs = build_target_specs(contract, mappings=mappings, sessions=sessions)
    reader = CanonicalHistoricalReader(
        catalog=catalog,
        canonical_root=canonical_root,
        session_provider=lambda symbol, start, end: jm_sessions(
            session,
            symbol=symbol,
            start=start,
            end=end,
        ),
    )
    service = MarketDataService(session, canonical_reader=reader)
    result = assess_target_specs(specs, probe=market_data_probe(service))
    return {
        **result,
        "target_id": _TARGET_ID,
        "target_symbol": contract.symbol,
        "target_frequencies": [item.value for item in contract.frequencies],
        "target_window": {
            "start_trading_day": contract.start_trading_day.isoformat(),
            "end_trading_day": mappings[-1].trading_day.isoformat(),
        },
    }


def market_data_probe(service: MarketDataService) -> TargetProbe:
    if not isinstance(service, MarketDataService):
        raise TypeError("service must be a MarketDataService")

    def probe(spec: TargetSpec) -> TargetValidation:
        query = BarQuery(
            dataset_kind=spec.dataset.dataset_kind,
            symbol=spec.dataset.symbol,
            contract_or_series=spec.dataset.contract_or_series,
            frequency=spec.dataset.frequency,
            start=spec.start,
            end=spec.end,
            strict=True,
        )
        try:
            result = service.get_bars(query)
        except (DataCoreError, CatalogError, OSError, ValueError) as exc:
            reason = _validation_failure_reason(exc)
            return TargetValidation(
                valid=False,
                reason=reason,
                explicit_gap=reason == "catalog_gap",
            )
        if not isinstance(result, BarsResult):
            return TargetValidation(valid=False, reason="market_data_result_invalid")
        if (
            result.requested_window != (spec.start, spec.end)
            or result.data_type is not spec.dataset.dataset_kind
            or result.derived_frequency is not None
            or result.source_datasets != (spec.dataset,)
            or any(bar.frequency is not spec.dataset.frequency for bar in result.bars)
        ):
            return TargetValidation(valid=False, reason="market_data_frequency_mismatch")
        return TargetValidation(valid=True, reason="canonical_validated")

    return probe


def load_target_contract(path: Path) -> TargetContract:
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise ValueError("TASK07_TARGET_CONTRACT_INVALID") from exc
    if not isinstance(payload, Mapping) or set(payload) != {"schema_version", "targets"}:
        raise ValueError("TASK07_TARGET_CONTRACT_INVALID")
    targets = payload.get("targets")
    if payload.get("schema_version") != 1 or not isinstance(targets, list) or len(targets) != 1:
        raise ValueError("TASK07_TARGET_CONTRACT_INVALID")
    target = targets[0]
    if not isinstance(target, Mapping) or set(target) != _TARGET_FIELDS:
        raise ValueError("TASK07_TARGET_CONTRACT_INVALID")
    main_contract = target.get("main_contract")
    if not isinstance(main_contract, Mapping) or set(main_contract) != _MAIN_CONTRACT_FIELDS:
        raise ValueError("TASK07_TARGET_CONTRACT_INVALID")
    expected = {
        "target_id": _TARGET_ID,
        "provider": "rqdata",
        "symbol": "jm",
        "continuous_series": "JM.MAIN",
        "dataset_kinds": ["continuous", "actual_dominant"],
        "adjustment": "none",
        "schema_version": "canonical-bar-v1",
        "end_policy": "latest_complete_main_contract_map_day",
    }
    if any(target.get(key) != value for key, value in expected.items()):
        raise ValueError("TASK07_TARGET_CONTRACT_INVALID")
    if dict(main_contract) != {
        "provider": "rqdata",
        "rank": 1,
        "rule": "volume_open_interest",
    }:
        raise ValueError("TASK07_TARGET_CONTRACT_INVALID")
    raw_frequencies = target.get("frequencies")
    if not isinstance(raw_frequencies, list) or raw_frequencies != list(BAR_FREQUENCY_VALUES):
        raise ValueError("TASK07_TARGET_CONTRACT_INVALID")
    try:
        start_trading_day = date.fromisoformat(str(target["start_trading_day"]))
    except (TypeError, ValueError) as exc:
        raise ValueError("TASK07_TARGET_CONTRACT_INVALID") from exc
    if start_trading_day != date(2013, 3, 22):
        raise ValueError("TASK07_TARGET_CONTRACT_INVALID")
    return TargetContract(
        symbol="jm",
        continuous_series="JM.MAIN",
        frequencies=tuple(BarFrequency(value) for value in raw_frequencies),
        start_trading_day=start_trading_day,
    )


def build_target_specs(
    contract: TargetContract,
    *,
    mappings: Sequence[MainContractTarget],
    sessions: Sequence[TargetSession],
) -> tuple[TargetSpec, ...]:
    if not isinstance(contract, TargetContract):
        raise ValueError("TASK07_TARGET_CONTRACT_INVALID")
    mapping_rows = tuple(mappings)
    session_rows = tuple(sessions)
    if not mapping_rows or not session_rows:
        raise ValueError("TASK07_TARGET_WINDOW_INVALID")
    if tuple(sorted(mapping_rows, key=lambda item: item.trading_day)) != mapping_rows:
        raise ValueError("TASK07_MAIN_CONTRACT_MAP_INVALID")
    if len({item.trading_day for item in mapping_rows}) != len(mapping_rows):
        raise ValueError("TASK07_MAIN_CONTRACT_MAP_INVALID")
    sessions_by_day: dict[date, list[TargetSession]] = {}
    for item in session_rows:
        sessions_by_day.setdefault(item.trading_day, []).append(item)
    if set(sessions_by_day) != {item.trading_day for item in mapping_rows}:
        raise ValueError("TASK07_MAIN_CONTRACT_MAP_INCOMPLETE")

    overall_start = min(item.start for item in session_rows)
    overall_end = max(item.end for item in session_rows)
    specs: list[TargetSpec] = []
    for frequency in contract.frequencies:
        specs.append(
            _target_spec(
                contract,
                dataset_kind=DatasetKind.CONTINUOUS,
                contract_or_series=contract.continuous_series,
                frequency=frequency,
                start=overall_start,
                end=overall_end,
            )
        )
    for frequency in contract.frequencies:
        for segment, covered_days in _frequency_mapping_segments(
            mapping_rows,
            frequency=frequency,
        ):
            segment_sessions = [
                session
                for trading_day in covered_days
                for session in sessions_by_day[trading_day]
            ]
            specs.append(
                _target_spec(
                    contract,
                    dataset_kind=DatasetKind.ACTUAL_DOMINANT,
                    contract_or_series=segment[0].actual_contract,
                    frequency=frequency,
                    start=min(item.start for item in segment_sessions),
                    end=max(item.end for item in segment_sessions),
                )
            )
    return tuple(sorted(specs, key=_target_sort_key))


def assess_target_specs(
    specs: Sequence[TargetSpec],
    *,
    probe: TargetProbe,
) -> dict[str, Any]:
    target_specs = tuple(specs)
    if not target_specs or not callable(probe):
        raise ValueError("TASK07_TARGET_ASSESSMENT_INVALID")
    results: list[dict[str, Any]] = []
    for spec in target_specs:
        validation = probe(spec)
        if not isinstance(validation, TargetValidation):
            raise ValueError("TASK07_TARGET_VALIDATION_INVALID")
        if validation.valid:
            status = TargetCanonicalStatus.KEEP_CANONICAL
            reason = validation.reason
        elif spec.dataset.frequency in {
            BarFrequency.M1,
            BarFrequency.D1,
            BarFrequency.W1,
        }:
            status = (
                TargetCanonicalStatus.REGISTER_DATA_GAP
                if validation.explicit_gap
                else TargetCanonicalStatus.REDOWNLOAD_DIRECT
            )
            reason = validation.reason
        else:
            source = probe(spec.source_1m())
            if not isinstance(source, TargetValidation):
                raise ValueError("TASK07_TARGET_VALIDATION_INVALID")
            if source.valid:
                status = TargetCanonicalStatus.REBUILD_AGGREGATE
                reason = validation.reason
            else:
                status = TargetCanonicalStatus.REGISTER_DATA_GAP
                reason = "canonical_1m_untrusted"
        results.append(_target_result(spec, status=status, reason=reason))

    repair_count = sum(
        item["status"]
        in {
            TargetCanonicalStatus.REDOWNLOAD_DIRECT.value,
            TargetCanonicalStatus.REBUILD_AGGREGATE.value,
        }
        for item in results
    )
    all_keep = all(
        item["status"] == TargetCanonicalStatus.KEEP_CANONICAL.value
        for item in results
    )
    return {
        "Stage_C": (
            "NO_DATA_WRITE_REQUIRED" if all_keep else "EXACT_GAP_PLAN_REQUIRED"
        ),
        "writes_authorized": False,
        "repair_count": repair_count,
        "targets": results,
    }


def _mapping_segments(
    mappings: Sequence[MainContractTarget],
) -> tuple[tuple[MainContractTarget, ...], ...]:
    segments: list[list[MainContractTarget]] = []
    for item in mappings:
        if not segments or segments[-1][-1].actual_contract != item.actual_contract:
            segments.append([item])
        else:
            segments[-1].append(item)
    return tuple(tuple(segment) for segment in segments)


def _target_sessions(
    session: Session,
    *,
    contract: TargetContract,
    mappings: Sequence[MainContractTarget],
) -> tuple[TargetSession, ...]:
    first_day = mappings[0].trading_day
    last_day = mappings[-1].trading_day
    start = datetime.combine(first_day - timedelta(days=7), time.min, tzinfo=UTC)
    end = datetime.combine(last_day + timedelta(days=2), time.max, tzinfo=UTC)
    expected_days = {item.trading_day for item in mappings}
    resolved = tuple(
        item
        for item in jm_sessions(
            session,
            symbol=contract.symbol,
            start=start,
            end=end,
        )
        if first_day <= item.trading_day <= last_day
    )
    sessions = tuple(
        TargetSession(item.trading_day, item.start, item.end) for item in resolved
    )
    if {item.trading_day for item in sessions} != expected_days:
        raise ValueError("TASK07_MAIN_CONTRACT_MAP_INCOMPLETE")
    return sessions


def _validation_failure_reason(exc: Exception) -> str:
    if isinstance(exc, DataCoreError):
        reason = exc.facts.get("reason")
        if isinstance(reason, str) and reason.strip():
            return reason.strip()
        return exc.code.lower()
    if isinstance(exc, CatalogError):
        return exc.code.lower()
    return type(exc).__name__.lower()


def _frequency_mapping_segments(
    mappings: Sequence[MainContractTarget],
    *,
    frequency: BarFrequency,
) -> tuple[tuple[tuple[MainContractTarget, ...], tuple[date, ...]], ...]:
    if frequency is not BarFrequency.W1:
        return tuple(
            (segment, tuple(item.trading_day for item in segment))
            for segment in _mapping_segments(mappings)
        )

    weekly: list[tuple[MainContractTarget, tuple[date, ...]]] = []
    by_week: dict[tuple[int, int], list[MainContractTarget]] = {}
    for item in mappings:
        iso = item.trading_day.isocalendar()
        by_week.setdefault((iso.year, iso.week), []).append(item)
    for week in sorted(by_week):
        rows = by_week[week]
        weekly.append((rows[-1], tuple(item.trading_day for item in rows)))

    grouped: list[tuple[list[MainContractTarget], list[date]]] = []
    for mapping, covered_days in weekly:
        if not grouped or grouped[-1][0][-1].actual_contract != mapping.actual_contract:
            grouped.append(([mapping], list(covered_days)))
        else:
            grouped[-1][0].append(mapping)
            grouped[-1][1].extend(covered_days)
    return tuple(
        (tuple(segment), tuple(covered_days))
        for segment, covered_days in grouped
    )


def _target_spec(
    contract: TargetContract,
    *,
    dataset_kind: DatasetKind,
    contract_or_series: str,
    frequency: BarFrequency,
    start: datetime,
    end: datetime,
) -> TargetSpec:
    return TargetSpec(
        dataset=DatasetKey(
            provider="rqdata",
            dataset_kind=dataset_kind,
            symbol=contract.symbol,
            contract_or_series=contract_or_series,
            frequency=frequency,
            adjustment="none",
            schema_version="canonical-bar-v1",
        ),
        start=start,
        end=end,
    )


def _target_sort_key(spec: TargetSpec) -> tuple[int, str, int, datetime]:
    return (
        0 if spec.dataset.dataset_kind is DatasetKind.CONTINUOUS else 1,
        spec.dataset.contract_or_series,
        _FREQUENCY_ORDER[spec.dataset.frequency.value],
        spec.start,
    )


def _target_result(
    spec: TargetSpec,
    *,
    status: TargetCanonicalStatus,
    reason: str,
) -> dict[str, Any]:
    return {
        "dataset": {
            "provider": spec.dataset.provider,
            "dataset_kind": spec.dataset.dataset_kind.value,
            "symbol": spec.dataset.symbol,
            "contract_or_series": spec.dataset.contract_or_series,
            "frequency": spec.dataset.frequency.value,
            "adjustment": spec.dataset.adjustment,
            "schema_version": spec.dataset.schema_version,
        },
        "window": {
            "start": spec.start.isoformat(),
            "end": spec.end.isoformat(),
        },
        "status": status.value,
        "reason": reason,
        "authorized": False,
    }


def _aware_utc(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("TASK07_TARGET_DATETIME_INVALID")
    return value.astimezone(UTC)
