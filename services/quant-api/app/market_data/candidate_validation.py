from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum
from types import MappingProxyType

from .subing_calibration import HorizonEvaluation
from .subing_lifecycle import ConfirmationSource
from .subing_lifecycle_research_service import SubingLifecycleResearchResult


_FUNNEL_KEYS = (
    "DATA_READY",
    "DIRECTION_CONTEXT_ALIGNED",
    "SETUP_ARMED",
    "TRIGGER_OBSERVED",
    "ENTRY_CONFIRMED",
)
_CONFIRMATION_KEYS = tuple(source.name for source in ConfirmationSource)
_OVERLAP_KEYS = ("V1_AND_V2", "V2_ONLY", "V1_ONLY")
_TRADING_DAY_SPAN_KEYS = ("SAME_DAY", "CROSS_DAY")
_HORIZONS = (3, 5, 8)
_CANDIDATE_ID = "subing_lifecycle_v2_candidate_v1"
_POLICY_ID = "subing_lifecycle_v2_research_v1"
_FORMULA_VERSION = "subing_lifecycle_v2"
_PROTOCOL_ID = "candidate_validation_v1"
_QUALITY_FLAGS = frozenset(
    {
        "PROSPECTIVE_OOS_PENDING",
        "ROLLING_FOLD_WITHOUT_ENTRY",
        "HORIZON_WITHOUT_SAMPLE",
    }
)


class CandidateWindowKind(StrEnum):
    RETROSPECTIVE = "retrospective"
    ROLLING_REFERENCE = "rolling_reference"
    ROLLING_TEST = "rolling_test"
    PROSPECTIVE_OOS = "prospective_oos"


class ProspectiveOosStatus(StrEnum):
    PENDING = "pending"
    EVALUATED = "evaluated"


@dataclass(frozen=True, slots=True)
class CandidateWindowResult:
    window_id: str
    window_kind: CandidateWindowKind
    since: date
    through: date
    products: tuple[str, ...]
    segment_count: int
    evaluable_boundary_count: int
    funnel_counts: Mapping[str, int]
    funnel_count_units: Mapping[str, str]
    confirmation_source_counts: Mapping[str, int]
    v1_v2_overlap_counts: Mapping[str, int]
    v2_to_v1_lead_bars: tuple[int, ...]
    confirmed_trading_day_span_counts: Mapping[str, int]
    risk_reason_counts: Mapping[str, int]
    recovery_reason_counts: Mapping[str, int]
    close_reason_counts: Mapping[str, int]
    horizon_summary: Mapping[int, HorizonEvaluation]

    def __post_init__(self) -> None:
        if not isinstance(self.window_id, str) or not self.window_id.strip():
            raise ValueError("CANDIDATE_WINDOW_INVALID")
        try:
            kind = CandidateWindowKind(self.window_kind)
        except (TypeError, ValueError) as exc:
            raise ValueError("CANDIDATE_WINDOW_INVALID") from exc
        if (
            type(self.since) is not date
            or type(self.through) is not date
            or self.since > self.through
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
            or not _nonnegative_int(self.evaluable_boundary_count)
        ):
            raise ValueError("CANDIDATE_WINDOW_INVALID")
        funnel = _freeze_counts(self.funnel_counts, expected_keys=_FUNNEL_KEYS)
        units = _freeze_units(self.funnel_count_units, expected_keys=_FUNNEL_KEYS)
        confirmation = _freeze_counts(
            self.confirmation_source_counts,
            expected_keys=_CONFIRMATION_KEYS,
        )
        overlap = _freeze_counts(
            self.v1_v2_overlap_counts,
            expected_keys=_OVERLAP_KEYS,
        )
        day_span = _freeze_counts(
            self.confirmed_trading_day_span_counts,
            expected_keys=_TRADING_DAY_SPAN_KEYS,
        )
        risk = _freeze_counts(self.risk_reason_counts)
        recovery = _freeze_counts(self.recovery_reason_counts)
        close = _freeze_counts(self.close_reason_counts)
        if funnel["DATA_READY"] != self.evaluable_boundary_count:
            raise ValueError("CANDIDATE_WINDOW_INVALID")
        lead_bars = tuple(self.v2_to_v1_lead_bars)
        if any(not _nonnegative_int(value) for value in lead_bars):
            raise ValueError("CANDIDATE_WINDOW_INVALID")
        horizons = dict(self.horizon_summary)
        if tuple(horizons) != _HORIZONS or any(
            not isinstance(value, HorizonEvaluation) for value in horizons.values()
        ):
            raise ValueError("CANDIDATE_WINDOW_INVALID")
        object.__setattr__(self, "window_id", self.window_id.strip())
        object.__setattr__(self, "window_kind", kind)
        object.__setattr__(self, "funnel_counts", funnel)
        object.__setattr__(self, "funnel_count_units", units)
        object.__setattr__(self, "confirmation_source_counts", confirmation)
        object.__setattr__(self, "v1_v2_overlap_counts", overlap)
        object.__setattr__(self, "v2_to_v1_lead_bars", lead_bars)
        object.__setattr__(self, "confirmed_trading_day_span_counts", day_span)
        object.__setattr__(self, "risk_reason_counts", risk)
        object.__setattr__(self, "recovery_reason_counts", recovery)
        object.__setattr__(self, "close_reason_counts", close)
        object.__setattr__(self, "horizon_summary", MappingProxyType(horizons))


@dataclass(frozen=True, slots=True)
class RollingCandidateFold:
    fold_id: str
    reference: CandidateWindowResult
    test: CandidateWindowResult

    def __post_init__(self) -> None:
        if (
            not isinstance(self.fold_id, str)
            or not self.fold_id.strip()
            or not isinstance(self.reference, CandidateWindowResult)
            or not isinstance(self.test, CandidateWindowResult)
            or self.reference.window_kind is not CandidateWindowKind.ROLLING_REFERENCE
            or self.test.window_kind is not CandidateWindowKind.ROLLING_TEST
        ):
            raise ValueError("CANDIDATE_ROLLING_FOLD_INVALID")
        object.__setattr__(self, "fold_id", self.fold_id.strip())


@dataclass(frozen=True, slots=True)
class CandidateStabilitySummary:
    fold_count: int
    folds_with_entries: int
    entry_count_min: int
    entry_count_max: int
    entry_count_median: Decimal

    def __post_init__(self) -> None:
        if (
            not _nonnegative_int(self.fold_count)
            or not _nonnegative_int(self.folds_with_entries)
            or self.folds_with_entries > self.fold_count
            or not _nonnegative_int(self.entry_count_min)
            or not _nonnegative_int(self.entry_count_max)
            or self.entry_count_min > self.entry_count_max
            or not isinstance(self.entry_count_median, Decimal)
            or not self.entry_count_median.is_finite()
            or self.entry_count_median < 0
        ):
            raise ValueError("CANDIDATE_STABILITY_INVALID")


@dataclass(frozen=True, slots=True)
class ProspectiveOosResult:
    status: ProspectiveOosStatus
    first_trading_day: date
    through: date
    result: CandidateWindowResult | None

    def __post_init__(self) -> None:
        try:
            status = ProspectiveOosStatus(self.status)
        except (TypeError, ValueError) as exc:
            raise ValueError("CANDIDATE_PROSPECTIVE_OOS_INVALID") from exc
        if type(self.first_trading_day) is not date or type(self.through) is not date:
            raise ValueError("CANDIDATE_PROSPECTIVE_OOS_INVALID")
        if status is ProspectiveOosStatus.PENDING:
            if self.result is not None or self.through >= self.first_trading_day:
                raise ValueError("CANDIDATE_PROSPECTIVE_OOS_INVALID")
        elif (
            not isinstance(self.result, CandidateWindowResult)
            or self.result.window_kind is not CandidateWindowKind.PROSPECTIVE_OOS
            or self.result.since != self.first_trading_day
            or self.result.through != self.through
            or self.through < self.first_trading_day
        ):
            raise ValueError("CANDIDATE_PROSPECTIVE_OOS_INVALID")
        object.__setattr__(self, "status", status)


@dataclass(frozen=True, slots=True)
class CandidateValidationReport:
    schema_version: int
    candidate_id: str
    policy_id: str
    formula_version: str
    protocol_id: str
    research_only: bool
    symbol: str
    retrospective: CandidateWindowResult
    rolling_folds: tuple[RollingCandidateFold, ...]
    rolling_stability: CandidateStabilitySummary
    prospective_oos: ProspectiveOosResult
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
            or not isinstance(self.retrospective, CandidateWindowResult)
            or self.retrospective.window_kind is not CandidateWindowKind.RETROSPECTIVE
            or not folds
            or any(not isinstance(fold, RollingCandidateFold) for fold in folds)
            or len({fold.fold_id for fold in folds}) != len(folds)
            or not isinstance(self.rolling_stability, CandidateStabilitySummary)
            or self.rolling_stability != summarize_rolling_stability(folds)
            or not isinstance(self.prospective_oos, ProspectiveOosResult)
            or any(flag not in _QUALITY_FLAGS for flag in flags)
            or len(set(flags)) != len(flags)
        ):
            raise ValueError("CANDIDATE_VALIDATION_REPORT_INVALID")
        object.__setattr__(self, "rolling_folds", folds)
        object.__setattr__(self, "quality_flags", flags)


def project_lifecycle_window(
    *,
    window_id: str,
    window_kind: CandidateWindowKind,
    since: date,
    through: date,
    source: SubingLifecycleResearchResult,
) -> CandidateWindowResult:
    if not isinstance(source, SubingLifecycleResearchResult):
        raise TypeError("source must be SubingLifecycleResearchResult")
    return CandidateWindowResult(
        window_id=window_id,
        window_kind=window_kind,
        since=since,
        through=through,
        products=tuple(source.products),
        segment_count=source.segment_count,
        evaluable_boundary_count=source.evaluable_boundary_count,
        funnel_counts=source.funnel_counts,
        funnel_count_units=source.funnel_count_units,
        confirmation_source_counts=source.confirmation_source_counts,
        v1_v2_overlap_counts=source.v1_v2_overlap_counts,
        v2_to_v1_lead_bars=tuple(source.v2_to_v1_lead_bars),
        confirmed_trading_day_span_counts=source.confirmed_trading_day_span_counts,
        risk_reason_counts=source.risk_reason_counts,
        recovery_reason_counts=source.recovery_reason_counts,
        close_reason_counts=source.close_reason_counts,
        horizon_summary=source.horizon_summary,
    )


def summarize_rolling_stability(
    folds: Sequence[RollingCandidateFold],
) -> CandidateStabilitySummary:
    normalized = tuple(folds)
    if not normalized or any(not isinstance(fold, RollingCandidateFold) for fold in normalized):
        raise ValueError("CANDIDATE_STABILITY_INVALID")
    counts = sorted(fold.test.funnel_counts["ENTRY_CONFIRMED"] for fold in normalized)
    midpoint = len(counts) // 2
    median = (
        Decimal(counts[midpoint])
        if len(counts) % 2
        else (Decimal(counts[midpoint - 1]) + Decimal(counts[midpoint])) / Decimal(2)
    )
    return CandidateStabilitySummary(
        fold_count=len(normalized),
        folds_with_entries=sum(count > 0 for count in counts),
        entry_count_min=counts[0],
        entry_count_max=counts[-1],
        entry_count_median=median,
    )


def _freeze_counts(
    values: Mapping[str, int],
    *,
    expected_keys: tuple[str, ...] | None = None,
) -> Mapping[str, int]:
    copied = dict(values)
    if (
        (expected_keys is not None and tuple(copied) != expected_keys)
        or any(not isinstance(key, str) or not key for key in copied)
        or any(not _nonnegative_int(value) for value in copied.values())
    ):
        raise ValueError("CANDIDATE_WINDOW_INVALID")
    return MappingProxyType(copied)


def _freeze_units(
    values: Mapping[str, str],
    *,
    expected_keys: tuple[str, ...],
) -> Mapping[str, str]:
    copied = dict(values)
    if tuple(copied) != expected_keys or any(
        not isinstance(value, str) or not value for value in copied.values()
    ):
        raise ValueError("CANDIDATE_WINDOW_INVALID")
    return MappingProxyType(copied)


def _nonnegative_int(value: object) -> bool:
    return type(value) is int and value >= 0
