"""Immutable Candidate Validation projections for exact JDJ 1m research."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum
from types import MappingProxyType

from .jdj_research import JdjResearchResult
from .price_outcome import PriceHorizonEvaluation


_HORIZONS = (3, 5, 8, 20)
_EMBARGO_DAY = date(2026, 8, 21)
_POLICY_ID = "jdj_1m_policy_v1"
_FORMULA_VERSION = "jdj_1m_v1"
_PROTOCOL_ID = "jdj_candidate_validation_v1"
_CANDIDATE_SOURCE_KINDS = {
    "jdj_trend_follow_1m_candidate_v1": "jdj_trend_follow_triggered",
    "jdj_trend_reentry_6_1m_candidate_v1": (
        "jdj_trend_reentry_6_triggered"
    ),
    "jdj_key_level_breakout_1m_candidate_v1": (
        "jdj_key_level_breakout_triggered"
    ),
}
_QUALITY_FLAGS = frozenset(
    {
        "PROSPECTIVE_OOS_PENDING",
        "ROLLING_FOLD_WITHOUT_EVENT",
        "HORIZON_WITHOUT_SAMPLE",
    }
)


class JdjCandidateWindowKind(StrEnum):
    RETROSPECTIVE = "retrospective"
    ROLLING_REFERENCE = "rolling_reference"
    ROLLING_TEST = "rolling_test"
    PROSPECTIVE_OOS = "prospective_oos"


@dataclass(frozen=True, slots=True)
class JdjCandidateWindowResult:
    window_id: str
    window_kind: JdjCandidateWindowKind
    since: date
    through: date
    products: tuple[str, ...]
    segment_count: int
    evaluable_bar_count: int
    trigger_count_long: int
    trigger_count_short: int
    horizon_summary: Mapping[int, PriceHorizonEvaluation]

    def __post_init__(self) -> None:
        try:
            kind = JdjCandidateWindowKind(self.window_kind)
        except (TypeError, ValueError) as exc:
            raise ValueError("JDJ_CANDIDATE_WINDOW_INVALID") from exc
        horizons = dict(self.horizon_summary)
        if (
            type(self.window_id) is not str
            or not self.window_id.strip()
            or type(self.since) is not date
            or type(self.through) is not date
            or self.since > self.through
            or self.since <= _EMBARGO_DAY <= self.through
            or type(self.products) is not tuple
            or not self.products
            or any(
                type(product) is not str
                or not product
                or not product.isascii()
                or not product.isalpha()
                or product != product.lower()
                for product in self.products
            )
            or not _nonnegative_int(self.segment_count)
            or not _nonnegative_int(self.evaluable_bar_count)
            or not _nonnegative_int(self.trigger_count_long)
            or not _nonnegative_int(self.trigger_count_short)
            or tuple(horizons) != _HORIZONS
            or any(
                not _valid_horizon(value) for value in horizons.values()
            )
        ):
            raise ValueError("JDJ_CANDIDATE_WINDOW_INVALID")
        object.__setattr__(self, "window_id", self.window_id.strip())
        object.__setattr__(self, "window_kind", kind)
        object.__setattr__(
            self,
            "horizon_summary",
            MappingProxyType(horizons),
        )


@dataclass(frozen=True, slots=True)
class JdjRollingCandidateFold:
    fold_id: str
    reference: JdjCandidateWindowResult
    test: JdjCandidateWindowResult

    def __post_init__(self) -> None:
        if (
            type(self.fold_id) is not str
            or not self.fold_id.strip()
            or not isinstance(self.reference, JdjCandidateWindowResult)
            or not isinstance(self.test, JdjCandidateWindowResult)
            or self.reference.window_kind
            is not JdjCandidateWindowKind.ROLLING_REFERENCE
            or self.test.window_kind
            is not JdjCandidateWindowKind.ROLLING_TEST
        ):
            raise ValueError("JDJ_CANDIDATE_ROLLING_FOLD_INVALID")
        object.__setattr__(self, "fold_id", self.fold_id.strip())


@dataclass(frozen=True, slots=True)
class JdjCandidateStabilitySummary:
    fold_count: int
    folds_with_events: int
    event_count_min: int
    event_count_max: int
    event_count_median: Decimal

    def __post_init__(self) -> None:
        if (
            not _nonnegative_int(self.fold_count)
            or not _nonnegative_int(self.folds_with_events)
            or self.folds_with_events > self.fold_count
            or not _nonnegative_int(self.event_count_min)
            or not _nonnegative_int(self.event_count_max)
            or self.event_count_min > self.event_count_max
            or not isinstance(self.event_count_median, Decimal)
            or not self.event_count_median.is_finite()
            or self.event_count_median < 0
        ):
            raise ValueError("JDJ_CANDIDATE_STABILITY_INVALID")


class JdjProspectiveOosStatus(StrEnum):
    PENDING = "pending"
    EVALUATED = "evaluated"


@dataclass(frozen=True, slots=True)
class JdjProspectiveOosResult:
    status: JdjProspectiveOosStatus
    first_trading_day: date
    through: date
    result: JdjCandidateWindowResult | None

    def __post_init__(self) -> None:
        try:
            status = JdjProspectiveOosStatus(self.status)
        except (TypeError, ValueError) as exc:
            raise ValueError("JDJ_CANDIDATE_PROSPECTIVE_OOS_INVALID") from exc
        if (
            type(self.first_trading_day) is not date
            or type(self.through) is not date
        ):
            raise ValueError("JDJ_CANDIDATE_PROSPECTIVE_OOS_INVALID")
        if status is JdjProspectiveOosStatus.PENDING:
            if self.result is not None or self.through >= self.first_trading_day:
                raise ValueError("JDJ_CANDIDATE_PROSPECTIVE_OOS_INVALID")
        elif (
            not isinstance(self.result, JdjCandidateWindowResult)
            or self.result.window_kind
            is not JdjCandidateWindowKind.PROSPECTIVE_OOS
            or self.result.since != self.first_trading_day
            or self.result.through != self.through
            or self.through < self.first_trading_day
        ):
            raise ValueError("JDJ_CANDIDATE_PROSPECTIVE_OOS_INVALID")
        object.__setattr__(self, "status", status)


@dataclass(frozen=True, slots=True)
class JdjCandidateValidationReport:
    schema_version: int
    candidate_id: str
    source_event_kind: str
    policy_id: str
    formula_version: str
    protocol_id: str
    research_only: bool
    symbol: str
    retrospective: JdjCandidateWindowResult
    rolling_folds: tuple[JdjRollingCandidateFold, ...]
    rolling_stability: JdjCandidateStabilitySummary
    prospective_oos: JdjProspectiveOosResult
    quality_flags: tuple[str, ...]

    def __post_init__(self) -> None:
        folds = tuple(self.rolling_folds)
        flags = tuple(self.quality_flags)
        if (
            type(self.schema_version) is not int
            or self.schema_version != 1
            or _CANDIDATE_SOURCE_KINDS.get(self.candidate_id)
            != self.source_event_kind
            or self.policy_id != _POLICY_ID
            or self.formula_version != _FORMULA_VERSION
            or self.protocol_id != _PROTOCOL_ID
            or self.research_only is not True
            or type(self.symbol) is not str
            or not self.symbol
            or not self.symbol.isascii()
            or not self.symbol.isalpha()
            or self.symbol != self.symbol.lower()
            or not isinstance(self.retrospective, JdjCandidateWindowResult)
            or self.retrospective.window_kind
            is not JdjCandidateWindowKind.RETROSPECTIVE
            or not folds
            or any(
                not isinstance(fold, JdjRollingCandidateFold)
                for fold in folds
            )
            or len({fold.fold_id for fold in folds}) != len(folds)
            or not isinstance(
                self.rolling_stability,
                JdjCandidateStabilitySummary,
            )
            or self.rolling_stability
            != summarize_jdj_rolling_stability(folds)
            or not isinstance(self.prospective_oos, JdjProspectiveOosResult)
            or any(flag not in _QUALITY_FLAGS for flag in flags)
            or len(set(flags)) != len(flags)
        ):
            raise ValueError("JDJ_CANDIDATE_VALIDATION_REPORT_INVALID")
        object.__setattr__(self, "rolling_folds", folds)
        object.__setattr__(self, "quality_flags", flags)


def project_jdj_window(
    *,
    window_id: str,
    window_kind: JdjCandidateWindowKind,
    since: date,
    through: date,
    source: JdjResearchResult,
) -> JdjCandidateWindowResult:
    if not isinstance(source, JdjResearchResult):
        raise TypeError("source must be JdjResearchResult")
    return JdjCandidateWindowResult(
        window_id=window_id,
        window_kind=window_kind,
        since=since,
        through=through,
        products=tuple(source.products),
        segment_count=source.segment_count,
        evaluable_bar_count=source.evaluable_bar_count,
        trigger_count_long=source.trigger_count_long,
        trigger_count_short=source.trigger_count_short,
        horizon_summary=source.horizon_summary,
    )


def summarize_jdj_rolling_stability(
    folds: Sequence[JdjRollingCandidateFold],
) -> JdjCandidateStabilitySummary:
    normalized = tuple(folds)
    if not normalized or any(
        not isinstance(fold, JdjRollingCandidateFold) for fold in normalized
    ):
        raise ValueError("JDJ_CANDIDATE_STABILITY_INVALID")
    counts = sorted(
        fold.test.trigger_count_long + fold.test.trigger_count_short
        for fold in normalized
    )
    midpoint = len(counts) // 2
    median = (
        Decimal(counts[midpoint])
        if len(counts) % 2
        else (
            Decimal(counts[midpoint - 1]) + Decimal(counts[midpoint])
        )
        / Decimal(2)
    )
    return JdjCandidateStabilitySummary(
        fold_count=len(normalized),
        folds_with_events=sum(count > 0 for count in counts),
        event_count_min=counts[0],
        event_count_max=counts[-1],
        event_count_median=median,
    )


def _nonnegative_int(value: object) -> bool:
    return type(value) is int and value >= 0


def _valid_horizon(value: object) -> bool:
    if not isinstance(value, PriceHorizonEvaluation):
        return False
    medians = (
        value.median_directional_return_bps,
        value.median_mfe_bps,
        value.median_mae_bps,
    )
    if not _nonnegative_int(value.sample_count):
        return False
    if value.sample_count == 0:
        return all(item is None for item in medians)
    return all(isinstance(item, Decimal) and item.is_finite() for item in medians)
