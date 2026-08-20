from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from types import MappingProxyType
from typing import TypeGuard


_SUBING = "subing_lifecycle_v2_candidate_v1"
_N = "n_structure_5m_candidate_v1"
_CANDIDATES = (_SUBING, _N)
_PRODUCTS = (
    "a", "ag", "al", "ao", "ap", "au", "b", "bu", "bz", "c",
    "cf", "cj", "cu", "eb", "ec", "eg", "fg", "fu", "hc", "i",
    "j", "jd", "jm", "l", "lc", "lh", "m", "ma", "ni", "oi",
    "p", "pb", "pd", "pf", "pg", "pk", "pl", "pp", "pr", "ps",
    "pt", "px", "rb", "rm", "rs", "ru", "sa", "sc", "sf", "sh",
    "si", "sm", "sn", "sr", "ss", "ta", "ur", "v", "y", "zn",
)
_HORIZONS = (3, 5, 8)
_CANDIDATE_FIELDS = {
    _SUBING: (
        "subing_lifecycle",
        "5m_ready_boundary",
        "same_trading_day_only",
        "candidate_validation_v1",
        "entry_confirmed",
    ),
    _N: (
        "n_structure",
        "5m_canonical_bar",
        "same_rank1_segment",
        "n_structure_validation_v1",
        "n_completed",
    ),
}
_METRIC_FLAGS = ("EVALUABLE_UNIT_DIFFERS", "HORIZON_SEMANTICS_DIFFERS")
_QUALITY_FLAG_ORDER = (
    "CROSS_SYMBOL_SOURCE_UNAVAILABLE",
    "BASELINE_PROSPECTIVE_PENDING_SUBING",
    "BASELINE_PROSPECTIVE_PENDING_N",
    "SYMBOL_WITHOUT_EVENT",
    "HORIZON_WITHOUT_SAMPLE",
)


class CandidateSymbolStatus(StrEnum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class CommonPriceHorizonSummary:
    sample_count: int
    median_directional_return_bps: Decimal | None
    median_mfe_bps: Decimal | None
    median_mae_bps: Decimal | None

    def __post_init__(self) -> None:
        metrics = (
            self.median_directional_return_bps,
            self.median_mfe_bps,
            self.median_mae_bps,
        )
        if not _nonnegative_int(self.sample_count) or (
            self.sample_count == 0
            and any(metric is not None for metric in metrics)
        ) or (
            self.sample_count > 0
            and any(not _finite_decimal(metric) for metric in metrics)
        ):
            raise ValueError("MULTI_CANDIDATE_REPORT_INVALID")


@dataclass(frozen=True, slots=True)
class CandidateSymbolRobustness:
    candidate_id: str
    source_kind: str
    symbol: str
    status: CandidateSymbolStatus
    reason_code: str | None
    event_count: int | None
    evaluable_count: int | None
    evaluable_unit: str
    event_rate_per_1000_evaluable: Decimal | None
    horizon_semantics: str
    horizon_summary: Mapping[int, CommonPriceHorizonSummary] | None

    def __post_init__(self) -> None:
        identity = _CANDIDATE_FIELDS.get(self.candidate_id)
        try:
            status = CandidateSymbolStatus(self.status)
        except (TypeError, ValueError) as exc:
            raise ValueError("MULTI_CANDIDATE_REPORT_INVALID") from exc
        if (
            identity is None
            or self.source_kind != identity[0]
            or self.evaluable_unit != identity[1]
            or self.horizon_semantics != identity[2]
            or not _symbol(self.symbol)
        ):
            raise ValueError("MULTI_CANDIDATE_REPORT_INVALID")
        if status is CandidateSymbolStatus.UNAVAILABLE:
            if (
                self.reason_code != "MULTI_CANDIDATE_SOURCE_UNAVAILABLE"
                or self.event_count is not None
                or self.evaluable_count is not None
                or self.event_rate_per_1000_evaluable is not None
                or self.horizon_summary is not None
            ):
                raise ValueError("MULTI_CANDIDATE_REPORT_INVALID")
            object.__setattr__(self, "status", status)
            return
        if (
            self.reason_code is not None
            or not _nonnegative_int(self.event_count)
            or not _nonnegative_int(self.evaluable_count)
        ):
            raise ValueError("MULTI_CANDIDATE_REPORT_INVALID")
        horizons = _freeze_horizons(self.horizon_summary)
        assert self.event_count is not None
        assert self.evaluable_count is not None
        expected_rate = (
            None
            if self.evaluable_count == 0
            else Decimal(self.event_count)
            * Decimal(1000)
            / Decimal(self.evaluable_count)
        )
        if (
            self.evaluable_count > 0
            and type(self.event_rate_per_1000_evaluable) is not Decimal
        ) or self.event_rate_per_1000_evaluable != expected_rate:
            raise ValueError("MULTI_CANDIDATE_REPORT_INVALID")
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "horizon_summary", horizons)


@dataclass(frozen=True, slots=True)
class CandidateTemporalDossier:
    candidate_id: str
    candidate_protocol_id: str
    source_kind: str
    anchor_symbol: str
    retrospective_since: date
    retrospective_through: date
    event_unit: str
    retrospective_event_count: int
    rolling_fold_count: int
    folds_with_events: int
    test_event_count_min: int
    test_event_count_median: Decimal
    test_event_count_max: int
    prospective_status: str
    prospective_first_trading_day: date
    prospective_through: date
    horizon_semantics: str
    horizon_summary: Mapping[int, CommonPriceHorizonSummary]
    source_quality_flags: tuple[str, ...]

    def __post_init__(self) -> None:
        identity = _CANDIDATE_FIELDS.get(self.candidate_id)
        flags = tuple(self.source_quality_flags)
        if (
            identity is None
            or self.source_kind != identity[0]
            or self.candidate_protocol_id != identity[3]
            or self.event_unit != identity[4]
            or self.horizon_semantics != identity[2]
            or self.anchor_symbol != "jm"
            or type(self.retrospective_since) is not date
            or type(self.retrospective_through) is not date
            or self.retrospective_since > self.retrospective_through
            or not _nonnegative_int(self.retrospective_event_count)
            or not _positive_int(self.rolling_fold_count)
            or not _nonnegative_int(self.folds_with_events)
            or self.folds_with_events > self.rolling_fold_count
            or not _nonnegative_int(self.test_event_count_min)
            or not _nonnegative_int(self.test_event_count_max)
            or self.test_event_count_min > self.test_event_count_max
            or not _finite_decimal(self.test_event_count_median)
            or not (
                Decimal(self.test_event_count_min)
                <= self.test_event_count_median
                <= Decimal(self.test_event_count_max)
            )
            or self.prospective_status not in {"pending", "evaluated"}
            or type(self.prospective_first_trading_day) is not date
            or type(self.prospective_through) is not date
            or any(not isinstance(flag, str) or not flag for flag in flags)
            or len(set(flags)) != len(flags)
        ):
            raise ValueError("MULTI_CANDIDATE_REPORT_INVALID")
        object.__setattr__(self, "horizon_summary", _freeze_horizons(self.horizon_summary))
        object.__setattr__(self, "source_quality_flags", flags)


@dataclass(frozen=True, slots=True)
class CandidateRelationshipSummary:
    source_candidate_id: str
    target_candidate_id: str
    source_event_count: int
    target_event_count: int
    exact_same_direction_count: int
    exact_opposite_direction_count: int
    within_3_same_direction_source_count: int
    within_5_same_direction_source_count: int
    within_8_same_direction_source_count: int
    nearest_match_count_within_8: int
    signed_distance_min: int | None
    signed_distance_median: Decimal | None
    signed_distance_max: int | None
    target_earlier_count: int
    target_same_boundary_count: int
    target_later_count: int
    same_trading_day_count: int
    cross_trading_day_count: int

    def __post_init__(self) -> None:
        counts = (
            self.source_event_count,
            self.target_event_count,
            self.exact_same_direction_count,
            self.exact_opposite_direction_count,
            self.within_3_same_direction_source_count,
            self.within_5_same_direction_source_count,
            self.within_8_same_direction_source_count,
            self.nearest_match_count_within_8,
            self.target_earlier_count,
            self.target_same_boundary_count,
            self.target_later_count,
            self.same_trading_day_count,
            self.cross_trading_day_count,
        )
        if (
            self.source_candidate_id not in _CANDIDATES
            or self.target_candidate_id not in _CANDIDATES
            or self.source_candidate_id == self.target_candidate_id
            or any(not _nonnegative_int(value) for value in counts)
            or not (
                self.within_3_same_direction_source_count
                <= self.within_5_same_direction_source_count
                <= self.within_8_same_direction_source_count
                == self.nearest_match_count_within_8
                <= self.source_event_count
            )
        ):
            raise ValueError("MULTI_CANDIDATE_REPORT_INVALID")
        if self.nearest_match_count_within_8 == 0:
            valid_distance = (
                self.signed_distance_min is None
                and self.signed_distance_median is None
                and self.signed_distance_max is None
                and self.target_earlier_count == 0
                and self.target_same_boundary_count == 0
                and self.target_later_count == 0
                and self.same_trading_day_count == 0
                and self.cross_trading_day_count == 0
            )
        else:
            minimum = self.signed_distance_min
            median = self.signed_distance_median
            maximum = self.signed_distance_max
            valid_distance = (
                type(minimum) is int
                and _finite_decimal(median)
                and type(maximum) is int
                and minimum <= median <= maximum
                and self.target_earlier_count
                + self.target_same_boundary_count
                + self.target_later_count
                == self.nearest_match_count_within_8
                and self.same_trading_day_count + self.cross_trading_day_count
                == self.nearest_match_count_within_8
            )
        if not valid_distance:
            raise ValueError("MULTI_CANDIDATE_REPORT_INVALID")


@dataclass(frozen=True, slots=True)
class HorizonSignSummary:
    symbols_with_samples: int
    positive_median_return_symbols: int
    zero_median_return_symbols: int
    negative_median_return_symbols: int

    def __post_init__(self) -> None:
        values = (
            self.symbols_with_samples,
            self.positive_median_return_symbols,
            self.zero_median_return_symbols,
            self.negative_median_return_symbols,
        )
        if any(not _nonnegative_int(value) for value in values) or (
            self.positive_median_return_symbols
            + self.zero_median_return_symbols
            + self.negative_median_return_symbols
            != self.symbols_with_samples
        ):
            raise ValueError("MULTI_CANDIDATE_REPORT_INVALID")


@dataclass(frozen=True, slots=True)
class CrossSymbolCandidateSummary:
    candidate_id: str
    product_count: int
    available_product_count: int
    unavailable_product_count: int
    symbols_with_events: int
    symbols_without_events: int
    event_rate_available_count: int
    event_rate_min: Decimal | None
    event_rate_median: Decimal | None
    event_rate_max: Decimal | None
    horizon_sign_summary: Mapping[int, HorizonSignSummary]

    def __post_init__(self) -> None:
        rates = (self.event_rate_min, self.event_rate_median, self.event_rate_max)
        if (
            self.candidate_id not in _CANDIDATES
            or self.product_count != 60
            or any(
                not _nonnegative_int(value)
                for value in (
                    self.available_product_count,
                    self.unavailable_product_count,
                    self.symbols_with_events,
                    self.symbols_without_events,
                    self.event_rate_available_count,
                )
            )
            or self.available_product_count + self.unavailable_product_count != 60
            or self.symbols_with_events + self.symbols_without_events
            != self.available_product_count
            or self.event_rate_available_count > self.available_product_count
        ):
            raise ValueError("MULTI_CANDIDATE_REPORT_INVALID")
        if self.event_rate_available_count == 0:
            valid_rates = all(rate is None for rate in rates)
        else:
            minimum = self.event_rate_min
            median = self.event_rate_median
            maximum = self.event_rate_max
            valid_rates = (
                _finite_decimal(minimum)
                and _finite_decimal(median)
                and _finite_decimal(maximum)
                and minimum <= median <= maximum
            )
        signs = dict(self.horizon_sign_summary)
        if not valid_rates or tuple(signs) != _HORIZONS or any(
            not isinstance(value, HorizonSignSummary) for value in signs.values()
        ):
            raise ValueError("MULTI_CANDIDATE_REPORT_INVALID")
        object.__setattr__(self, "horizon_sign_summary", MappingProxyType(signs))


@dataclass(frozen=True, slots=True)
class MultiCandidateRobustnessReport:
    schema_version: int
    protocol_id: str
    frozen_at: datetime
    research_only: bool
    readonly: bool
    anchor_symbol: str
    common_since: date
    common_through: date
    temporal_dossiers: tuple[CandidateTemporalDossier, ...]
    cross_symbol_results: tuple[CandidateSymbolRobustness, ...]
    cross_symbol_summaries: tuple[CrossSymbolCandidateSummary, ...]
    relationships: tuple[CandidateRelationshipSummary, ...]
    metric_compatibility_flags: tuple[str, ...]
    quality_flags: tuple[str, ...]

    def __post_init__(self) -> None:
        temporal = tuple(self.temporal_dossiers)
        rows = tuple(self.cross_symbol_results)
        summaries = tuple(self.cross_symbol_summaries)
        relationships = tuple(self.relationships)
        metric_flags = tuple(self.metric_compatibility_flags)
        quality_flags = tuple(self.quality_flags)
        expected_rows = tuple((_SUBING, symbol) for symbol in _PRODUCTS) + tuple(
            (_N, symbol) for symbol in _PRODUCTS
        )
        expected_quality = tuple(
            flag for flag in _QUALITY_FLAG_ORDER if flag in quality_flags
        )
        if (
            type(self.schema_version) is not int
            or self.schema_version != 1
            or self.protocol_id != "multi_candidate_robustness_v1"
            or self.frozen_at != datetime.fromisoformat("2026-08-20T21:33:00+08:00")
            or self.research_only is not True
            or self.readonly is not True
            or self.anchor_symbol != "jm"
            or self.common_since != date(2023, 1, 1)
            or self.common_through != date(2026, 8, 18)
            or tuple(item.candidate_id for item in temporal) != _CANDIDATES
            or tuple((item.candidate_id, item.symbol) for item in rows) != expected_rows
            or tuple(item.candidate_id for item in summaries) != _CANDIDATES
            or tuple(
                (item.source_candidate_id, item.target_candidate_id)
                for item in relationships
            )
            != ((_SUBING, _N), (_N, _SUBING))
            or metric_flags != _METRIC_FLAGS
            or quality_flags != expected_quality
            or len(set(quality_flags)) != len(quality_flags)
        ):
            raise ValueError("MULTI_CANDIDATE_REPORT_INVALID")
        object.__setattr__(self, "temporal_dossiers", temporal)
        object.__setattr__(self, "cross_symbol_results", rows)
        object.__setattr__(self, "cross_symbol_summaries", summaries)
        object.__setattr__(self, "relationships", relationships)
        object.__setattr__(self, "metric_compatibility_flags", metric_flags)
        object.__setattr__(self, "quality_flags", quality_flags)


def _freeze_horizons(
    values: Mapping[int, CommonPriceHorizonSummary] | None,
) -> Mapping[int, CommonPriceHorizonSummary]:
    if values is None:
        raise ValueError("MULTI_CANDIDATE_REPORT_INVALID")
    copied = dict(values)
    if tuple(copied) != _HORIZONS or any(
        not isinstance(value, CommonPriceHorizonSummary) for value in copied.values()
    ):
        raise ValueError("MULTI_CANDIDATE_REPORT_INVALID")
    return MappingProxyType(copied)


def _symbol(value: object) -> bool:
    return (
        isinstance(value, str)
        and bool(value)
        and value.isascii()
        and value.isalpha()
        and value == value.lower()
    )


def _nonnegative_int(value: object) -> bool:
    return type(value) is int and value >= 0


def _positive_int(value: object) -> bool:
    return type(value) is int and value > 0


def _finite_decimal(value: object) -> TypeGuard[Decimal]:
    return type(value) is Decimal and value.is_finite()
