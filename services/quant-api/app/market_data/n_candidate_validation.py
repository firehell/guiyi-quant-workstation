from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum
from types import MappingProxyType

from .n_structure_research_service import NStructureResearchResult
from .price_outcome import PriceHorizonEvaluation


_COMPLETED_N_KEYS = ("up", "down")
_N_BREAK_KEYS = ("n2_origin_broken", "origin_broken")
_STRUCTURE_ESTABLISHED_KEYS = ("bull", "bear", "range")
_STRUCTURE_BREAK_KEYS = ("bull", "bear")
_HORIZONS = (3, 5, 8)
_EMBARGO_DAY = date(2026, 8, 20)
_CANDIDATE_ID = "n_structure_5m_candidate_v1"
_POLICY_ID = "n_structure_5m_v1"
_FORMULA_VERSION = "n_structure_v1"
_PROTOCOL_ID = "n_structure_validation_v1"
_QUALITY_FLAGS = frozenset(
    {
        "PROSPECTIVE_OOS_PENDING",
        "ROLLING_FOLD_WITHOUT_COMPLETED_N",
        "HORIZON_WITHOUT_SAMPLE",
    }
)


class NCandidateWindowKind(StrEnum):
    RETROSPECTIVE = "retrospective"
    ROLLING_REFERENCE = "rolling_reference"
    ROLLING_TEST = "rolling_test"
    PROSPECTIVE_OOS = "prospective_oos"


class NProspectiveOosStatus(StrEnum):
    PENDING = "pending"
    EVALUATED = "evaluated"


@dataclass(frozen=True, slots=True)
class NCandidateWindowResult:
    window_id: str
    window_kind: NCandidateWindowKind
    since: date
    through: date
    products: tuple[str, ...]
    segment_count: int
    evaluable_bar_count: int
    confirmed_pivot_count: int
    ambiguous_outside_reset_count: int
    incomplete_attempt_replaced_count: int
    completed_n_counts: Mapping[str, int]
    n_break_counts: Mapping[str, int]
    range_band_reentry_count: int
    structure_established_counts: Mapping[str, int]
    structure_break_counts: Mapping[str, int]
    horizon_summary: Mapping[int, PriceHorizonEvaluation]

    def __post_init__(self) -> None:
        try:
            kind = NCandidateWindowKind(self.window_kind)
        except (TypeError, ValueError) as exc:
            raise ValueError("N_CANDIDATE_WINDOW_INVALID") from exc
        if (
            not isinstance(self.window_id, str)
            or not self.window_id.strip()
            or type(self.since) is not date
            or type(self.through) is not date
            or self.since > self.through
            or self.since <= _EMBARGO_DAY <= self.through
            or not isinstance(self.products, tuple)
            or not self.products
            or any(
                not isinstance(product, str)
                or not product
                or not product.isascii()
                or not product.isalpha()
                or product != product.lower()
                for product in self.products
            )
            or not _nonnegative_int(self.segment_count)
            or not _nonnegative_int(self.evaluable_bar_count)
            or not _nonnegative_int(self.confirmed_pivot_count)
            or not _nonnegative_int(self.ambiguous_outside_reset_count)
            or not _nonnegative_int(self.incomplete_attempt_replaced_count)
            or not _nonnegative_int(self.range_band_reentry_count)
        ):
            raise ValueError("N_CANDIDATE_WINDOW_INVALID")
        completed = _freeze_counts(
            self.completed_n_counts,
            expected_keys=_COMPLETED_N_KEYS,
        )
        n_breaks = _freeze_counts(
            self.n_break_counts,
            expected_keys=_N_BREAK_KEYS,
        )
        established = _freeze_counts(
            self.structure_established_counts,
            expected_keys=_STRUCTURE_ESTABLISHED_KEYS,
        )
        structure_breaks = _freeze_counts(
            self.structure_break_counts,
            expected_keys=_STRUCTURE_BREAK_KEYS,
        )
        horizons = dict(self.horizon_summary)
        if tuple(horizons) != _HORIZONS or any(
            not _valid_horizon(value) for value in horizons.values()
        ):
            raise ValueError("N_CANDIDATE_WINDOW_INVALID")
        object.__setattr__(self, "window_id", self.window_id.strip())
        object.__setattr__(self, "window_kind", kind)
        object.__setattr__(self, "completed_n_counts", completed)
        object.__setattr__(self, "n_break_counts", n_breaks)
        object.__setattr__(self, "structure_established_counts", established)
        object.__setattr__(self, "structure_break_counts", structure_breaks)
        object.__setattr__(self, "horizon_summary", MappingProxyType(horizons))


@dataclass(frozen=True, slots=True)
class NRollingCandidateFold:
    fold_id: str
    reference: NCandidateWindowResult
    test: NCandidateWindowResult

    def __post_init__(self) -> None:
        if (
            not isinstance(self.fold_id, str)
            or not self.fold_id.strip()
            or not isinstance(self.reference, NCandidateWindowResult)
            or not isinstance(self.test, NCandidateWindowResult)
            or self.reference.window_kind is not NCandidateWindowKind.ROLLING_REFERENCE
            or self.test.window_kind is not NCandidateWindowKind.ROLLING_TEST
        ):
            raise ValueError("N_CANDIDATE_ROLLING_FOLD_INVALID")
        object.__setattr__(self, "fold_id", self.fold_id.strip())


@dataclass(frozen=True, slots=True)
class NCandidateStabilitySummary:
    fold_count: int
    folds_with_completed_n: int
    completed_n_min: int
    completed_n_max: int
    completed_n_median: Decimal

    def __post_init__(self) -> None:
        if (
            not _nonnegative_int(self.fold_count)
            or not _nonnegative_int(self.folds_with_completed_n)
            or self.folds_with_completed_n > self.fold_count
            or not _nonnegative_int(self.completed_n_min)
            or not _nonnegative_int(self.completed_n_max)
            or self.completed_n_min > self.completed_n_max
            or not isinstance(self.completed_n_median, Decimal)
            or not self.completed_n_median.is_finite()
            or self.completed_n_median < 0
        ):
            raise ValueError("N_CANDIDATE_STABILITY_INVALID")


@dataclass(frozen=True, slots=True)
class NProspectiveOosResult:
    status: NProspectiveOosStatus
    first_trading_day: date
    through: date
    result: NCandidateWindowResult | None

    def __post_init__(self) -> None:
        try:
            status = NProspectiveOosStatus(self.status)
        except (TypeError, ValueError) as exc:
            raise ValueError("N_CANDIDATE_PROSPECTIVE_OOS_INVALID") from exc
        if type(self.first_trading_day) is not date or type(self.through) is not date:
            raise ValueError("N_CANDIDATE_PROSPECTIVE_OOS_INVALID")
        if status is NProspectiveOosStatus.PENDING:
            if self.result is not None or self.through >= self.first_trading_day:
                raise ValueError("N_CANDIDATE_PROSPECTIVE_OOS_INVALID")
        elif (
            not isinstance(self.result, NCandidateWindowResult)
            or self.result.window_kind is not NCandidateWindowKind.PROSPECTIVE_OOS
            or self.result.since != self.first_trading_day
            or self.result.through != self.through
            or self.through < self.first_trading_day
        ):
            raise ValueError("N_CANDIDATE_PROSPECTIVE_OOS_INVALID")
        object.__setattr__(self, "status", status)


@dataclass(frozen=True, slots=True)
class NStructureCandidateValidationReport:
    schema_version: int
    candidate_id: str
    policy_id: str
    formula_version: str
    protocol_id: str
    research_only: bool
    symbol: str
    retrospective: NCandidateWindowResult
    rolling_folds: tuple[NRollingCandidateFold, ...]
    rolling_stability: NCandidateStabilitySummary
    prospective_oos: NProspectiveOosResult
    quality_flags: tuple[str, ...]

    def __post_init__(self) -> None:
        folds = tuple(self.rolling_folds)
        flags = tuple(self.quality_flags)
        if (
            type(self.schema_version) is not int
            or self.schema_version != 1
            or self.candidate_id != _CANDIDATE_ID
            or self.policy_id != _POLICY_ID
            or self.formula_version != _FORMULA_VERSION
            or self.protocol_id != _PROTOCOL_ID
            or self.research_only is not True
            or not isinstance(self.symbol, str)
            or not self.symbol
            or not self.symbol.isascii()
            or not self.symbol.isalpha()
            or self.symbol != self.symbol.lower()
            or not isinstance(self.retrospective, NCandidateWindowResult)
            or self.retrospective.window_kind is not NCandidateWindowKind.RETROSPECTIVE
            or not folds
            or any(not isinstance(fold, NRollingCandidateFold) for fold in folds)
            or len({fold.fold_id for fold in folds}) != len(folds)
            or not isinstance(self.rolling_stability, NCandidateStabilitySummary)
            or self.rolling_stability != summarize_n_rolling_stability(folds)
            or not isinstance(self.prospective_oos, NProspectiveOosResult)
            or any(flag not in _QUALITY_FLAGS for flag in flags)
            or len(set(flags)) != len(flags)
        ):
            raise ValueError("N_CANDIDATE_VALIDATION_REPORT_INVALID")
        object.__setattr__(self, "rolling_folds", folds)
        object.__setattr__(self, "quality_flags", flags)


def project_n_structure_window(
    *,
    window_id: str,
    window_kind: NCandidateWindowKind,
    since: date,
    through: date,
    source: NStructureResearchResult,
) -> NCandidateWindowResult:
    if not isinstance(source, NStructureResearchResult):
        raise TypeError("source must be NStructureResearchResult")
    return NCandidateWindowResult(
        window_id=window_id,
        window_kind=window_kind,
        since=since,
        through=through,
        products=tuple(source.products),
        segment_count=source.segment_count,
        evaluable_bar_count=source.evaluable_bar_count,
        confirmed_pivot_count=source.confirmed_pivot_count,
        ambiguous_outside_reset_count=source.ambiguous_outside_reset_count,
        incomplete_attempt_replaced_count=source.incomplete_attempt_replaced_count,
        completed_n_counts=source.completed_n_counts,
        n_break_counts=source.n_break_counts,
        range_band_reentry_count=source.range_band_reentry_count,
        structure_established_counts=source.structure_established_counts,
        structure_break_counts=source.structure_break_counts,
        horizon_summary=source.horizon_summary,
    )


def summarize_n_rolling_stability(
    folds: Sequence[NRollingCandidateFold],
) -> NCandidateStabilitySummary:
    normalized = tuple(folds)
    if not normalized or any(
        not isinstance(fold, NRollingCandidateFold) for fold in normalized
    ):
        raise ValueError("N_CANDIDATE_STABILITY_INVALID")
    counts = sorted(sum(fold.test.completed_n_counts.values()) for fold in normalized)
    midpoint = len(counts) // 2
    median = (
        Decimal(counts[midpoint])
        if len(counts) % 2
        else (Decimal(counts[midpoint - 1]) + Decimal(counts[midpoint])) / Decimal(2)
    )
    return NCandidateStabilitySummary(
        fold_count=len(normalized),
        folds_with_completed_n=sum(count > 0 for count in counts),
        completed_n_min=counts[0],
        completed_n_max=counts[-1],
        completed_n_median=median,
    )


def _freeze_counts(
    values: Mapping[str, int],
    *,
    expected_keys: tuple[str, ...],
) -> Mapping[str, int]:
    copied = dict(values)
    if tuple(copied) != expected_keys or any(
        not _nonnegative_int(value) for value in copied.values()
    ):
        raise ValueError("N_CANDIDATE_WINDOW_INVALID")
    return MappingProxyType(copied)


def _valid_horizon(value: object) -> bool:
    if not isinstance(value, PriceHorizonEvaluation):
        return False
    metrics = (
        value.median_directional_return_bps,
        value.median_mfe_bps,
        value.median_mae_bps,
    )
    if not _nonnegative_int(value.sample_count):
        return False
    if value.sample_count == 0:
        return all(metric is None for metric in metrics)
    return all(isinstance(metric, Decimal) and metric.is_finite() for metric in metrics)


def _nonnegative_int(value: object) -> bool:
    return type(value) is int and value >= 0
