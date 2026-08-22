from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Any, Never, TypeGuard

from app.core.env import PROJECT_ROOT  # type: ignore[import-untyped]

from app.core.exact_json_contract import load_exact_json
from app.research.jdj.jdj_candidate_validation_policy import (
    JdjCandidateValidationProtocolError,
    load_jdj_candidate_validation_protocol,
)
from app.market_data.operational_universe import ActiveUniverseError, load_active_products
from app.market_data.product_taxonomy import ProductTaxonomyError, load_product_taxonomy


_PROTOCOL_ID = "jdj_active60_robustness_v1"
_PROTOCOL_PATH = (
    PROJECT_ROOT / "data/research_protocols/jdj_active60_robustness_v1.json"
)
_CANDIDATES = (
    "jdj_trend_follow_1m_candidate_v1",
    "jdj_trend_reentry_6_1m_candidate_v1",
    "jdj_key_level_breakout_1m_candidate_v1",
)
_PRODUCTS = (
    "a", "ag", "al", "ao", "ap", "au", "b", "bu", "bz", "c",
    "cf", "cj", "cu", "eb", "ec", "eg", "fg", "fu", "hc", "i",
    "j", "jd", "jm", "l", "lc", "lh", "m", "ma", "ni", "oi",
    "p", "pb", "pd", "pf", "pg", "pk", "pl", "pp", "pr", "ps",
    "pt", "px", "rb", "rm", "rs", "ru", "sa", "sc", "sf", "sh",
    "si", "sm", "sn", "sr", "ss", "ta", "ur", "v", "y", "zn",
)
_SECTOR_GROUPS = {
    "agriculture": (
        "a", "ap", "b", "c", "cf", "cj", "jd", "lh", "m", "oi",
        "p", "pk", "rm", "rs", "sr", "y",
    ),
    "precious": ("ag", "au", "pd", "pt"),
    "nonferrous": ("al", "ao", "cu", "ni", "pb", "sn", "zn"),
    "energy": ("bu", "fu", "pg", "sc"),
    "chemical": (
        "bz", "eb", "eg", "l", "ma", "pf", "pl", "pp", "pr", "px",
        "ru", "sh", "ta", "ur", "v",
    ),
    "other": ("ec",),
    "building": ("fg", "sa"),
    "steel": ("hc", "rb", "ss"),
    "black": ("i", "j", "jm", "sf", "sm"),
    "new_energy": ("lc", "ps", "si"),
}
_FROZEN_AT = datetime.fromisoformat("2026-08-21T20:34:00+08:00")
_COMMON_SINCE = date(2023, 1, 1)
_COMMON_THROUGH = date(2026, 8, 20)
_EMBARGO_TRADING_DAYS = (date(2026, 8, 21),)
_PROSPECTIVE_FIRST_TRADING_DAY = date(2026, 8, 24)
_HORIZONS = (3, 5, 8, 20)
_YEARS = (2023, 2024, 2025, 2026)
_QUALITY_FLAG_ORDER = (
    "SOURCE_UNAVAILABLE_PRESENT",
    "SYMBOL_WITHOUT_EVENT",
    "HORIZON_WITHOUT_SAMPLE",
    "SHORT_HISTORY_PRESENT",
)
_SYMBOL_SECTORS = {
    symbol: sector
    for sector, products in _SECTOR_GROUPS.items()
    for symbol in products
}
_EXPECTED: dict[str, Any] = {
    "schema_version": 1,
    "protocol_id": _PROTOCOL_ID,
    "research_only": True,
    "readonly": True,
    "frozen_at": "2026-08-21T20:34:00+08:00",
    "candidate_ids": list(_CANDIDATES),
    "source_policy": "jdj_1m_policy_v1",
    "source_validation_protocol": "jdj_candidate_validation_v1",
    "common_retrospective": {
        "since": "2023-01-01",
        "through": "2026-08-20",
    },
    "embargo_trading_days": ["2026-08-21"],
    "prospective_oos": {"first_trading_day": "2026-08-24"},
    "prospective_consumed": False,
    "horizons_bars": [3, 5, 8, 20],
    "cross_symbol_products": list(_PRODUCTS),
    "sector_groups": {
        sector: list(products) for sector, products in _SECTOR_GROUPS.items()
    },
    "parameter_perturbation": False,
    "relationship_analysis": False,
    "automatic_ranking": False,
    "automatic_promotion": False,
}


class JdjActive60RobustnessProtocolError(ValueError):
    code = "JDJ_ACTIVE60_ROBUSTNESS_PROTOCOL_INVALID"

    def __init__(self) -> None:
        super().__init__(self.code)


@dataclass(frozen=True, slots=True)
class JdjActive60RobustnessProtocol:
    schema_version: int
    protocol_id: str
    research_only: bool
    readonly: bool
    frozen_at: datetime
    candidate_ids: tuple[str, ...]
    source_policy: str
    source_validation_protocol: str
    common_since: date
    common_through: date
    embargo_trading_days: tuple[date, ...]
    prospective_first_trading_day: date
    prospective_consumed: bool
    horizons_bars: tuple[int, ...]
    cross_symbol_products: tuple[str, ...]
    sector_groups: Mapping[str, tuple[str, ...]]
    parameter_perturbation: bool
    relationship_analysis: bool
    automatic_ranking: bool
    automatic_promotion: bool

    def __post_init__(self) -> None:
        sectors = dict(self.sector_groups)
        object.__setattr__(self, "sector_groups", MappingProxyType(sectors))
        require_exact_jdj_active60_robustness_protocol(self)


def require_exact_jdj_active60_robustness_protocol(
    value: object,
) -> JdjActive60RobustnessProtocol:
    if not isinstance(value, JdjActive60RobustnessProtocol):
        raise JdjActive60RobustnessProtocolError()
    if (
        type(value.schema_version) is not int
        or value.schema_version != 1
        or value.protocol_id != _PROTOCOL_ID
        or value.research_only is not True
        or value.readonly is not True
        or value.frozen_at != _FROZEN_AT
        or value.candidate_ids != _CANDIDATES
        or value.source_policy != "jdj_1m_policy_v1"
        or value.source_validation_protocol != "jdj_candidate_validation_v1"
        or value.common_since != _COMMON_SINCE
        or value.common_through != _COMMON_THROUGH
        or value.embargo_trading_days != _EMBARGO_TRADING_DAYS
        or value.prospective_first_trading_day
        != _PROSPECTIVE_FIRST_TRADING_DAY
        or value.prospective_consumed is not False
        or value.horizons_bars != _HORIZONS
        or value.cross_symbol_products != _PRODUCTS
        or tuple(value.sector_groups.items()) != tuple(_SECTOR_GROUPS.items())
        or value.parameter_perturbation is not False
        or value.relationship_analysis is not False
        or value.automatic_ranking is not False
        or value.automatic_promotion is not False
    ):
        raise JdjActive60RobustnessProtocolError()
    return value


@dataclass(frozen=True, slots=True)
class JdjActive60RobustnessRequest:
    protocol_id: str

    def __post_init__(self) -> None:
        if self.protocol_id != _PROTOCOL_ID:
            raise JdjActive60RobustnessProtocolError()


class JdjRobustnessStatus(StrEnum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class JdjRobustnessHorizonSummary:
    sample_count: int
    historical_positive_outcome_rate: Decimal | None
    median_directional_return_bps: Decimal | None
    median_mfe_bps: Decimal | None
    median_mae_bps: Decimal | None

    def __post_init__(self) -> None:
        metrics = (
            self.historical_positive_outcome_rate,
            self.median_directional_return_bps,
            self.median_mfe_bps,
            self.median_mae_bps,
        )
        if not _nonnegative_int(self.sample_count):
            _raise_report_invalid()
        if self.sample_count == 0:
            if any(metric is not None for metric in metrics):
                _raise_report_invalid()
            return
        if any(not _finite_decimal(metric) for metric in metrics):
            _raise_report_invalid()
        rate = self.historical_positive_outcome_rate
        assert rate is not None
        if not Decimal(0) <= rate <= Decimal(1):
            _raise_report_invalid()


@dataclass(frozen=True, slots=True)
class JdjRobustnessYearSummary:
    event_count: int
    horizon_sample_count: Mapping[int, int]
    horizon_positive_outcome_rate: Mapping[int, Decimal | None]
    horizon_median_directional_return_bps: Mapping[int, Decimal | None]

    def __post_init__(self) -> None:
        samples = dict(self.horizon_sample_count)
        rates = dict(self.horizon_positive_outcome_rate)
        medians = dict(self.horizon_median_directional_return_bps)
        if (
            not _nonnegative_int(self.event_count)
            or tuple(samples) != _HORIZONS
            or tuple(rates) != _HORIZONS
            or tuple(medians) != _HORIZONS
        ):
            _raise_report_invalid()
        for horizon in _HORIZONS:
            sample_count = samples[horizon]
            rate = rates[horizon]
            median = medians[horizon]
            if not _nonnegative_int(sample_count):
                _raise_report_invalid()
            if sample_count == 0:
                if rate is not None or median is not None:
                    _raise_report_invalid()
            elif (
                not _finite_decimal(rate)
                or not Decimal(0) <= rate <= Decimal(1)
                or not _finite_decimal(median)
            ):
                _raise_report_invalid()
        object.__setattr__(
            self,
            "horizon_sample_count",
            MappingProxyType(samples),
        )
        object.__setattr__(
            self,
            "horizon_positive_outcome_rate",
            MappingProxyType(rates),
        )
        object.__setattr__(
            self,
            "horizon_median_directional_return_bps",
            MappingProxyType(medians),
        )


@dataclass(frozen=True, slots=True)
class JdjRobustnessSymbolResult:
    candidate_id: str
    symbol: str
    sector: str
    status: JdjRobustnessStatus
    reason_code: str | None
    observed_since: date | None
    observed_through: date | None
    evaluable_bar_count: int | None
    event_count: int | None
    long_event_count: int | None
    short_event_count: int | None
    event_rate_per_1000_evaluable: Decimal | None
    horizon_summary: Mapping[int, JdjRobustnessHorizonSummary] | None
    yearly: Mapping[int, JdjRobustnessYearSummary] | None

    def __post_init__(self) -> None:
        try:
            status = JdjRobustnessStatus(self.status)
        except (TypeError, ValueError):
            _raise_report_invalid()
        if (
            self.candidate_id not in _CANDIDATES
            or self.symbol not in _PRODUCTS
            or self.sector != _SYMBOL_SECTORS[self.symbol]
        ):
            _raise_report_invalid()
        if status is JdjRobustnessStatus.UNAVAILABLE:
            nullable_values = (
                self.observed_since,
                self.observed_through,
                self.evaluable_bar_count,
                self.event_count,
                self.long_event_count,
                self.short_event_count,
                self.event_rate_per_1000_evaluable,
                self.horizon_summary,
                self.yearly,
            )
            if (
                self.reason_code != "JDJ_SOURCE_UNAVAILABLE"
                or any(value is not None for value in nullable_values)
            ):
                _raise_report_invalid()
            object.__setattr__(self, "status", status)
            return
        if (
            self.reason_code is not None
            or type(self.observed_since) is not date
            or type(self.observed_through) is not date
            or not (
                _COMMON_SINCE
                <= self.observed_since
                <= self.observed_through
                <= _COMMON_THROUGH
            )
            or not _nonnegative_int(self.evaluable_bar_count)
            or not _nonnegative_int(self.event_count)
            or not _nonnegative_int(self.long_event_count)
            or not _nonnegative_int(self.short_event_count)
        ):
            _raise_report_invalid()
        assert self.evaluable_bar_count is not None
        assert self.event_count is not None
        assert self.long_event_count is not None
        assert self.short_event_count is not None
        expected_rate = (
            None
            if self.evaluable_bar_count == 0
            else Decimal(self.event_count)
            * Decimal(1000)
            / Decimal(self.evaluable_bar_count)
        )
        if (
            self.long_event_count + self.short_event_count != self.event_count
            or (self.evaluable_bar_count == 0 and self.event_count != 0)
            or self.event_rate_per_1000_evaluable != expected_rate
            or (
                expected_rate is not None
                and not _finite_decimal(self.event_rate_per_1000_evaluable)
            )
        ):
            _raise_report_invalid()
        horizons = _freeze_horizon_summary(self.horizon_summary)
        yearly = _freeze_yearly(self.yearly)
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "horizon_summary", horizons)
        object.__setattr__(self, "yearly", yearly)


@dataclass(frozen=True, slots=True)
class JdjRobustnessSectorHorizonSummary:
    symbols_with_samples: int
    positive_median_symbol_count: int
    zero_median_symbol_count: int
    negative_median_symbol_count: int
    median_of_symbol_median_return_bps: Decimal | None

    def __post_init__(self) -> None:
        values = (
            self.symbols_with_samples,
            self.positive_median_symbol_count,
            self.zero_median_symbol_count,
            self.negative_median_symbol_count,
        )
        if (
            any(not _nonnegative_int(value) for value in values)
            or self.positive_median_symbol_count
            + self.zero_median_symbol_count
            + self.negative_median_symbol_count
            != self.symbols_with_samples
            or (
                self.symbols_with_samples == 0
                and self.median_of_symbol_median_return_bps is not None
            )
            or (
                self.symbols_with_samples > 0
                and not _finite_decimal(
                    self.median_of_symbol_median_return_bps
                )
            )
        ):
            _raise_report_invalid()


@dataclass(frozen=True, slots=True)
class JdjRobustnessSectorSummary:
    candidate_id: str
    sector: str
    symbol_count: int
    available_symbol_count: int
    symbols_with_events: int
    horizon_summary: Mapping[int, JdjRobustnessSectorHorizonSummary]

    def __post_init__(self) -> None:
        if (
            self.candidate_id not in _CANDIDATES
            or self.sector not in _SECTOR_GROUPS
            or self.symbol_count != len(_SECTOR_GROUPS[self.sector])
            or not _nonnegative_int(self.available_symbol_count)
            or self.available_symbol_count > self.symbol_count
            or not _nonnegative_int(self.symbols_with_events)
            or self.symbols_with_events > self.available_symbol_count
        ):
            _raise_report_invalid()
        horizons = dict(self.horizon_summary)
        if tuple(horizons) != _HORIZONS or any(
            not isinstance(value, JdjRobustnessSectorHorizonSummary)
            for value in horizons.values()
        ):
            _raise_report_invalid()
        object.__setattr__(
            self,
            "horizon_summary",
            MappingProxyType(horizons),
        )


@dataclass(frozen=True, slots=True)
class JdjActive60RobustnessReport:
    schema_version: int
    command: str
    protocol_id: str
    frozen_at: datetime
    research_only: bool
    readonly: bool
    common_since: date
    common_through: date
    embargo_trading_days: tuple[date, ...]
    prospective_first_trading_day: date
    prospective_consumed: bool
    candidate_ids: tuple[str, ...]
    cross_symbol_results: tuple[JdjRobustnessSymbolResult, ...]
    sector_summaries: tuple[JdjRobustnessSectorSummary, ...]
    quality_flags: tuple[str, ...]

    def __post_init__(self) -> None:
        rows = tuple(self.cross_symbol_results)
        sectors = tuple(self.sector_summaries)
        quality_flags = tuple(self.quality_flags)
        expected_rows = tuple(
            (candidate_id, symbol)
            for candidate_id in _CANDIDATES
            for symbol in _PRODUCTS
        )
        expected_sectors = tuple(
            (candidate_id, sector)
            for candidate_id in _CANDIDATES
            for sector in _SECTOR_GROUPS
        )
        expected_quality_flags = tuple(
            flag for flag in _QUALITY_FLAG_ORDER if flag in quality_flags
        )
        if (
            type(self.schema_version) is not int
            or self.schema_version != 1
            or self.command
            != (
                "guiyi research candidate-robustness "
                "--protocol jdj_active60_robustness_v1"
            )
            or self.protocol_id != _PROTOCOL_ID
            or self.frozen_at != _FROZEN_AT
            or self.research_only is not True
            or self.readonly is not True
            or self.common_since != _COMMON_SINCE
            or self.common_through != _COMMON_THROUGH
            or self.embargo_trading_days != _EMBARGO_TRADING_DAYS
            or self.prospective_first_trading_day
            != _PROSPECTIVE_FIRST_TRADING_DAY
            or self.prospective_consumed is not False
            or self.candidate_ids != _CANDIDATES
            or tuple((row.candidate_id, row.symbol) for row in rows)
            != expected_rows
            or any(not isinstance(row, JdjRobustnessSymbolResult) for row in rows)
            or tuple((item.candidate_id, item.sector) for item in sectors)
            != expected_sectors
            or any(
                not isinstance(item, JdjRobustnessSectorSummary)
                for item in sectors
            )
            or quality_flags != expected_quality_flags
            or len(set(quality_flags)) != len(quality_flags)
        ):
            _raise_report_invalid()
        object.__setattr__(self, "cross_symbol_results", rows)
        object.__setattr__(self, "sector_summaries", sectors)
        object.__setattr__(self, "quality_flags", quality_flags)


def load_jdj_active60_robustness_protocol(
    path: Path | None = None,
) -> JdjActive60RobustnessProtocol:
    payload = load_exact_json(
        path or _PROTOCOL_PATH,
        _EXPECTED,
        JdjActive60RobustnessProtocolError,
    )
    protocol = JdjActive60RobustnessProtocol(
        schema_version=payload["schema_version"],
        protocol_id=payload["protocol_id"],
        research_only=payload["research_only"],
        readonly=payload["readonly"],
        frozen_at=datetime.fromisoformat(payload["frozen_at"]),
        candidate_ids=tuple(payload["candidate_ids"]),
        source_policy=payload["source_policy"],
        source_validation_protocol=payload["source_validation_protocol"],
        common_since=date.fromisoformat(payload["common_retrospective"]["since"]),
        common_through=date.fromisoformat(
            payload["common_retrospective"]["through"]
        ),
        embargo_trading_days=tuple(
            date.fromisoformat(value) for value in payload["embargo_trading_days"]
        ),
        prospective_first_trading_day=date.fromisoformat(
            payload["prospective_oos"]["first_trading_day"]
        ),
        prospective_consumed=payload["prospective_consumed"],
        horizons_bars=tuple(payload["horizons_bars"]),
        cross_symbol_products=tuple(payload["cross_symbol_products"]),
        sector_groups=MappingProxyType(
            {
                sector: tuple(products)
                for sector, products in payload["sector_groups"].items()
            }
        ),
        parameter_perturbation=payload["parameter_perturbation"],
        relationship_analysis=payload["relationship_analysis"],
        automatic_ranking=payload["automatic_ranking"],
        automatic_promotion=payload["automatic_promotion"],
    )
    _require_current_sources(protocol)
    return protocol


def _require_current_sources(protocol: JdjActive60RobustnessProtocol) -> None:
    try:
        active_products = load_active_products()
        taxonomy = load_product_taxonomy()
        validation = load_jdj_candidate_validation_protocol()
    except (
        ActiveUniverseError,
        ProductTaxonomyError,
        JdjCandidateValidationProtocolError,
    ):
        raise JdjActive60RobustnessProtocolError() from None
    current_sector_groups = {
        sector: tuple(
            symbol
            for symbol in active_products
            if taxonomy[symbol].sector == sector
        )
        for sector in protocol.sector_groups
    }
    validation_candidate_ids = tuple(
        candidate.candidate_id for candidate in validation.candidates
    )
    if (
        active_products != protocol.cross_symbol_products
        or current_sector_groups != protocol.sector_groups
        or validation.retrospective_since != protocol.common_since
        or validation.retrospective_through != protocol.common_through
        or validation.embargo_trading_days != protocol.embargo_trading_days
        or validation.prospective_oos_first_trading_day
        != protocol.prospective_first_trading_day
        or validation.horizons_bars != protocol.horizons_bars
        or validation_candidate_ids != protocol.candidate_ids
    ):
        raise JdjActive60RobustnessProtocolError()


def _freeze_horizon_summary(
    value: Mapping[int, JdjRobustnessHorizonSummary] | None,
) -> Mapping[int, JdjRobustnessHorizonSummary]:
    if value is None:
        _raise_report_invalid()
    horizons = dict(value)
    if tuple(horizons) != _HORIZONS or any(
        not isinstance(summary, JdjRobustnessHorizonSummary)
        for summary in horizons.values()
    ):
        _raise_report_invalid()
    return MappingProxyType(horizons)


def _freeze_yearly(
    value: Mapping[int, JdjRobustnessYearSummary] | None,
) -> Mapping[int, JdjRobustnessYearSummary]:
    if value is None:
        _raise_report_invalid()
    yearly = dict(value)
    if tuple(yearly) != _YEARS or any(
        not isinstance(summary, JdjRobustnessYearSummary)
        for summary in yearly.values()
    ):
        _raise_report_invalid()
    return MappingProxyType(yearly)


def _nonnegative_int(value: object) -> bool:
    return type(value) is int and value >= 0


def _finite_decimal(value: object) -> TypeGuard[Decimal]:
    return type(value) is Decimal and value.is_finite()


def _raise_report_invalid() -> Never:
    raise ValueError("JDJ_ACTIVE60_ROBUSTNESS_REPORT_INVALID")
