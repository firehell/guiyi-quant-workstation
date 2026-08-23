"""Immutable result contracts for Main Force Mirror diagnostic Phase A."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Never, TypeGuard, TypeAlias, TypeVar


_PROTOCOL_ID = "main_force_mirror_diagnostic_phase_a_v1"
_MODEL_SUBPROTOCOL = "mfm_v3_readonly_training_probe_v1"
_UNIVERSE_SHA256 = "d2f7e8387fa9dd92b8720ed703de3a7bbc1ef79d0d75340b246783bab079fd1d"
_PRODUCTS = (
    "a", "ag", "al", "ao", "ap", "au", "b", "bu", "bz", "c",
    "cf", "cj", "cu", "eb", "ec", "eg", "fg", "fu", "hc", "i",
    "j", "jd", "jm", "l", "lc", "lh", "m", "ma", "ni", "oi",
    "p", "pb", "pd", "pf", "pg", "pk", "pl", "pp", "pr", "ps",
    "pt", "px", "rb", "rm", "rs", "ru", "sa", "sc", "sf", "sh",
    "si", "sm", "sn", "sr", "ss", "ta", "ur", "v", "y", "zn",
)
_PROFILES = ("balanced", "fast", "slow", "loose", "strict")
_FOLD_WINDOWS = (
    (date(2023, 1, 1), date(2024, 12, 31), date(2025, 1, 1), date(2025, 12, 31)),
    (date(2023, 1, 1), date(2025, 12, 31), date(2026, 1, 1), date(2026, 8, 18)),
)


class MainForceMirrorDiagnosticReportError(ValueError):
    code = "MFM_DIAGNOSTIC_REPORT_INVALID"

    def __init__(self) -> None:
        super().__init__(self.code)


class MainForceMirrorDiagnosticGate(StrEnum):
    STOP = "STOP"
    ALLOW_PHASE_FREEZE_DESIGN = "ALLOW_PHASE_FREEZE_DESIGN"


class MainForceMirrorDiagnosticStatus(StrEnum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"


class MainForceMirrorDiagnosticUnavailableReason(StrEnum):
    MARKET_SOURCE_UNAVAILABLE = "MARKET_SOURCE_UNAVAILABLE"
    MFM_V2_IDENTITY_CONFLICT = "MFM_V2_IDENTITY_CONFLICT"
    POINT_COVERAGE_INCOMPLETE = "POINT_COVERAGE_INCOMPLETE"
    NO_CAUTION_EPISODE = "NO_CAUTION_EPISODE"
    LABEL_BARRIER_INVALID = "LABEL_BARRIER_INVALID"
    LABEL_HORIZON_INCOMPLETE = "LABEL_HORIZON_INCOMPLETE"
    PHYSICAL_CONTRACT_CHANGED_BEFORE_LABEL = "PHYSICAL_CONTRACT_CHANGED_BEFORE_LABEL"
    INPUT_GAP_BEFORE_LABEL = "INPUT_GAP_BEFORE_LABEL"
    SPLIT_CLASS_UNAVAILABLE = "SPLIT_CLASS_UNAVAILABLE"
    FEATURE_UNAVAILABLE = "FEATURE_UNAVAILABLE"
    MODEL_CONVERGENCE_FAILED = "MODEL_CONVERGENCE_FAILED"
    MEMBER_DATASET_UNAVAILABLE = "MEMBER_DATASET_UNAVAILABLE"
    MEMBER_T_MINUS_1_UNAVAILABLE = "MEMBER_T_MINUS_1_UNAVAILABLE"
    MEMBER_IDENTITY_CONFLICT = "MEMBER_IDENTITY_CONFLICT"


class MainForceMirrorDiagnosticGateReason(StrEnum):
    SOURCE_UNAVAILABLE_PRESENT = "SOURCE_UNAVAILABLE_PRESENT"
    SAMPLE_FLOOR_FAILED = "SAMPLE_FLOOR_FAILED"
    BINARY_COVERAGE_INSUFFICIENT = "BINARY_COVERAGE_INSUFFICIENT"
    AMBIGUOUS_RATE_EXCEEDED = "AMBIGUOUS_RATE_EXCEEDED"
    SEQUENCE_UNSTABLE = "SEQUENCE_UNSTABLE"
    RIDGE_INCREMENT_INSUFFICIENT = "RIDGE_INCREMENT_INSUFFICIENT"
    NONLINEAR_INCREMENT_INSUFFICIENT = "NONLINEAR_INCREMENT_INSUFFICIENT"
    SEQUENCE_INCREMENT_INSUFFICIENT = "SEQUENCE_INCREMENT_INSUFFICIENT"
    NONLINEAR_AUC_INSUFFICIENT = "NONLINEAR_AUC_INSUFFICIENT"
    SIDE_GUARDRAIL_FAILED = "SIDE_GUARDRAIL_FAILED"
    MEMBER_FEASIBILITY_INSUFFICIENT = "MEMBER_FEASIBILITY_INSUFFICIENT"
    MODEL_UNAVAILABLE = "MODEL_UNAVAILABLE"


class MainForceMirrorDiagnosticBreakdownScope(StrEnum):
    GLOBAL = "global"
    PRODUCT = "product"
    YEAR = "year"
    SIDE = "side"
    FOLD = "fold"


class MainForceMirrorDiagnosticSide(StrEnum):
    LONG = "long"
    SHORT = "short"


class MainForceMirrorDiagnosticSequenceState(StrEnum):
    IDLE = "idle"
    BUILD = "build"
    PEAK = "peak"
    DECAY = "decay"
    LIQUIDATION = "liquidation"
    OPPOSITE_BUILD = "opposite_build"
    ACCUMULATED_REVERSAL = "accumulated_reversal"


class MainForceMirrorDiagnosticSequenceEvent(StrEnum):
    PEAK = "peak"
    DECAY = "decay"
    LIQUIDATION = "liquidation"
    OPPOSITE_BUILD = "opposite_build"
    ACCUMULATED_REVERSAL = "accumulated_reversal"


@dataclass(frozen=True, slots=True)
class MainForceMirrorDiagnosticBreakdownKey:
    scope: MainForceMirrorDiagnosticBreakdownScope
    product: str | None = None
    year: int | None = None
    side: MainForceMirrorDiagnosticSide | None = None
    fold: int | None = None

    def __post_init__(self) -> None:
        try:
            scope = MainForceMirrorDiagnosticBreakdownScope(self.scope)
            side = None if self.side is None else MainForceMirrorDiagnosticSide(self.side)
        except (TypeError, ValueError):
            _raise_report_invalid()
        dimensions = (self.product, self.year, side, self.fold)
        if scope is MainForceMirrorDiagnosticBreakdownScope.GLOBAL:
            valid = all(value is None for value in dimensions)
        elif scope is MainForceMirrorDiagnosticBreakdownScope.PRODUCT:
            valid = self.product in _PRODUCTS and all(
                value is None for value in dimensions[1:]
            )
        elif scope is MainForceMirrorDiagnosticBreakdownScope.YEAR:
            valid = self.year in (2023, 2024, 2025, 2026) and (
                self.product is None and side is None and self.fold is None
            )
        elif scope is MainForceMirrorDiagnosticBreakdownScope.SIDE:
            valid = side is not None and (
                self.product is None and self.year is None and self.fold is None
            )
        else:
            valid = self.fold in (1, 2) and (
                self.product is None and self.year is None and side is None
            )
        if not valid:
            _raise_report_invalid()
        object.__setattr__(self, "scope", scope)
        object.__setattr__(self, "side", side)


@dataclass(frozen=True, slots=True)
class MainForceMirrorDiagnosticValidationMetadata:
    source_mode: str
    frequency: str
    confirmed_only: bool
    active_universe_sha256: str
    known_retrospective_through: date
    prospective_consumed: bool
    available_product_count: int
    unavailable_product_count: int
    unknown_failure_count: int

    def __post_init__(self) -> None:
        if (
            self.source_mode != "actual_dominant"
            or self.frequency != "60m"
            or self.confirmed_only is not True
            or self.active_universe_sha256 != _UNIVERSE_SHA256
            or self.known_retrospective_through != date(2026, 8, 20)
            or self.prospective_consumed is not False
            or not _nonnegative_int(self.available_product_count)
            or not _nonnegative_int(self.unavailable_product_count)
            or self.available_product_count > 60
            or self.unavailable_product_count > 60
            or self.available_product_count + self.unavailable_product_count != 60
            or self.unknown_failure_count != 0
            or type(self.unknown_failure_count) is not int
        ):
            _raise_report_invalid()


@dataclass(frozen=True, slots=True)
class MainForceMirrorDiagnosticAvailableProductRow:
    symbol: str
    status: MainForceMirrorDiagnosticStatus
    observed_since: date
    observed_through: date
    confirmed_bar_count: int
    physical_contract_count: int

    def __post_init__(self) -> None:
        if (
            self.symbol not in _PRODUCTS
            or self.status != MainForceMirrorDiagnosticStatus.AVAILABLE
            or type(self.observed_since) is not date
            or type(self.observed_through) is not date
            or not date(2023, 1, 1)
            <= self.observed_since
            <= self.observed_through
            <= date(2026, 8, 20)
            or not _positive_int(self.confirmed_bar_count)
            or not _positive_int(self.physical_contract_count)
        ):
            _raise_report_invalid()
        object.__setattr__(self, "status", MainForceMirrorDiagnosticStatus.AVAILABLE)


@dataclass(frozen=True, slots=True)
class MainForceMirrorDiagnosticUnavailableProductRow:
    symbol: str
    status: MainForceMirrorDiagnosticStatus
    reason_code: MainForceMirrorDiagnosticUnavailableReason

    def __post_init__(self) -> None:
        try:
            status = MainForceMirrorDiagnosticStatus(self.status)
            reason = MainForceMirrorDiagnosticUnavailableReason(self.reason_code)
        except (TypeError, ValueError):
            _raise_report_invalid()
        if self.symbol not in _PRODUCTS or status is not MainForceMirrorDiagnosticStatus.UNAVAILABLE:
            _raise_report_invalid()
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "reason_code", reason)


MainForceMirrorDiagnosticProductRow: TypeAlias = (
    MainForceMirrorDiagnosticAvailableProductRow
    | MainForceMirrorDiagnosticUnavailableProductRow
)


@dataclass(frozen=True, slots=True)
class MainForceMirrorDiagnosticLabelBreakdown:
    key: MainForceMirrorDiagnosticBreakdownKey
    raw_sample_count: int
    kept_sample_count: int
    overlap_suppressed_count: int
    legacy_long_only_count: int
    legacy_short_only_count: int
    legacy_both_count: int
    legacy_neither_count: int
    adverse_first_count: int
    favorable_first_count: int
    ambiguous_count: int
    timeout_count: int
    censored_horizon_count: int
    censored_contract_change_count: int
    censored_input_gap_count: int

    def __post_init__(self) -> None:
        counts = tuple(
            getattr(self, field)
            for field in self.__dataclass_fields__
            if field != "key"
        )
        if (
            not isinstance(self.key, MainForceMirrorDiagnosticBreakdownKey)
            or any(not _nonnegative_int(value) for value in counts)
            or self.kept_sample_count + self.overlap_suppressed_count
            != self.raw_sample_count
            or self.legacy_long_only_count
            + self.legacy_short_only_count
            + self.legacy_both_count
            + self.legacy_neither_count
            != self.raw_sample_count
            or self.adverse_first_count
            + self.favorable_first_count
            + self.ambiguous_count
            + self.timeout_count
            + self.censored_horizon_count
            + self.censored_contract_change_count
            + self.censored_input_gap_count
            != self.kept_sample_count
        ):
            _raise_report_invalid()


@dataclass(frozen=True, slots=True)
class MainForceMirrorDiagnosticLabelSection:
    raw_sample_count: int
    sample_count: int
    overlap_suppressed_count: int
    long_sample_count: int
    short_sample_count: int
    duplicated_side_sample_count: int
    legacy_long_only_count: int
    legacy_short_only_count: int
    legacy_both_count: int
    legacy_neither_count: int
    adverse_first_count: int
    favorable_first_count: int
    ambiguous_count: int
    timeout_count: int
    censored_horizon_count: int
    censored_contract_change_count: int
    censored_input_gap_count: int
    resolved_coverage: Decimal
    ambiguous_rate: Decimal
    breakdowns: tuple[MainForceMirrorDiagnosticLabelBreakdown, ...]

    def __post_init__(self) -> None:
        counts = (
            self.raw_sample_count,
            self.sample_count,
            self.overlap_suppressed_count,
            self.long_sample_count,
            self.short_sample_count,
            self.duplicated_side_sample_count,
            self.legacy_long_only_count,
            self.legacy_short_only_count,
            self.legacy_both_count,
            self.legacy_neither_count,
            self.adverse_first_count,
            self.favorable_first_count,
            self.ambiguous_count,
            self.timeout_count,
            self.censored_horizon_count,
            self.censored_contract_change_count,
            self.censored_input_gap_count,
        )
        breakdowns = _require_breakdowns(
            self.breakdowns,
            MainForceMirrorDiagnosticLabelBreakdown,
        )
        global_breakdown = breakdowns[0]
        expected_resolved = (
            Decimal(0)
            if self.sample_count == 0
            else Decimal(self.adverse_first_count + self.favorable_first_count)
            / Decimal(self.sample_count)
        )
        expected_ambiguous = (
            Decimal(0)
            if self.sample_count == 0
            else Decimal(self.ambiguous_count) / Decimal(self.sample_count)
        )
        if (
            any(not _nonnegative_int(value) for value in counts)
            or self.sample_count + self.overlap_suppressed_count
            != self.raw_sample_count
            or self.legacy_long_only_count
            + self.legacy_short_only_count
            + self.legacy_both_count
            + self.legacy_neither_count
            != self.raw_sample_count
            or self.adverse_first_count
            + self.favorable_first_count
            + self.ambiguous_count
            + self.timeout_count
            + self.censored_horizon_count
            + self.censored_contract_change_count
            + self.censored_input_gap_count
            != self.sample_count
            or self.long_sample_count
            + self.short_sample_count
            - self.duplicated_side_sample_count
            != self.sample_count
            or self.resolved_coverage != expected_resolved
            or self.ambiguous_rate != expected_ambiguous
            or not _rate(expected_resolved)
            or not _rate(expected_ambiguous)
            or (
                global_breakdown.raw_sample_count,
                global_breakdown.kept_sample_count,
                global_breakdown.overlap_suppressed_count,
                global_breakdown.legacy_long_only_count,
                global_breakdown.legacy_short_only_count,
                global_breakdown.legacy_both_count,
                global_breakdown.legacy_neither_count,
                global_breakdown.adverse_first_count,
                global_breakdown.favorable_first_count,
                global_breakdown.ambiguous_count,
                global_breakdown.timeout_count,
                global_breakdown.censored_horizon_count,
                global_breakdown.censored_contract_change_count,
                global_breakdown.censored_input_gap_count,
            )
            != (
                self.raw_sample_count,
                self.sample_count,
                self.overlap_suppressed_count,
                self.legacy_long_only_count,
                self.legacy_short_only_count,
                self.legacy_both_count,
                self.legacy_neither_count,
                self.adverse_first_count,
                self.favorable_first_count,
                self.ambiguous_count,
                self.timeout_count,
                self.censored_horizon_count,
                self.censored_contract_change_count,
                self.censored_input_gap_count,
            )
        ):
            _raise_report_invalid()
        object.__setattr__(self, "breakdowns", breakdowns)


@dataclass(frozen=True, slots=True)
class MainForceMirrorDiagnosticSequenceTransitionCount:
    from_state: MainForceMirrorDiagnosticSequenceState
    to_state: MainForceMirrorDiagnosticSequenceState
    count: int

    def __post_init__(self) -> None:
        try:
            source = MainForceMirrorDiagnosticSequenceState(self.from_state)
            target = MainForceMirrorDiagnosticSequenceState(self.to_state)
        except (TypeError, ValueError):
            _raise_report_invalid()
        if source is target or not _nonnegative_int(self.count):
            _raise_report_invalid()
        object.__setattr__(self, "from_state", source)
        object.__setattr__(self, "to_state", target)


@dataclass(frozen=True, slots=True)
class MainForceMirrorDiagnosticSequenceEventCount:
    event_kind: MainForceMirrorDiagnosticSequenceEvent
    raw_count: int
    kept_count: int
    overlap_count: int

    def __post_init__(self) -> None:
        try:
            event_kind = MainForceMirrorDiagnosticSequenceEvent(self.event_kind)
        except (TypeError, ValueError):
            _raise_report_invalid()
        if (
            not _nonnegative_int(self.raw_count)
            or not _nonnegative_int(self.kept_count)
            or not _nonnegative_int(self.overlap_count)
            or self.overlap_count > self.kept_count
            or self.kept_count > self.raw_count
        ):
            _raise_report_invalid()
        object.__setattr__(self, "event_kind", event_kind)


@dataclass(frozen=True, slots=True)
class MainForceMirrorDiagnosticPrefixInvariance:
    checked_prefix_count: int
    matching_prefix_count: int
    mismatch_count: int

    def __post_init__(self) -> None:
        if (
            not _nonnegative_int(self.checked_prefix_count)
            or not _nonnegative_int(self.matching_prefix_count)
            or not _nonnegative_int(self.mismatch_count)
            or self.matching_prefix_count + self.mismatch_count
            != self.checked_prefix_count
        ):
            _raise_report_invalid()


@dataclass(frozen=True, slots=True)
class MainForceMirrorDiagnosticSequenceBreakdown:
    key: MainForceMirrorDiagnosticBreakdownKey
    raw_episode_count: int
    kept_episode_count: int
    overlap_suppressed_count: int
    transitions: tuple[MainForceMirrorDiagnosticSequenceTransitionCount, ...]
    events: tuple[MainForceMirrorDiagnosticSequenceEventCount, ...]
    prefix_invariance: MainForceMirrorDiagnosticPrefixInvariance

    def __post_init__(self) -> None:
        transitions = tuple(self.transitions)
        events = tuple(self.events)
        transition_keys = tuple((item.from_state, item.to_state) for item in transitions)
        event_keys = tuple(item.event_kind for item in events)
        if (
            not isinstance(self.key, MainForceMirrorDiagnosticBreakdownKey)
            or not _nonnegative_int(self.raw_episode_count)
            or not _nonnegative_int(self.kept_episode_count)
            or not _nonnegative_int(self.overlap_suppressed_count)
            or self.kept_episode_count + self.overlap_suppressed_count
            != self.raw_episode_count
            or any(
                not isinstance(item, MainForceMirrorDiagnosticSequenceTransitionCount)
                for item in transitions
            )
            or len(set(transition_keys)) != len(transition_keys)
            or any(
                not isinstance(item, MainForceMirrorDiagnosticSequenceEventCount)
                for item in events
            )
            or len(set(event_keys)) != len(event_keys)
            or tuple(
                event for event in MainForceMirrorDiagnosticSequenceEvent if event in event_keys
            )
            != event_keys
            or not isinstance(
                self.prefix_invariance,
                MainForceMirrorDiagnosticPrefixInvariance,
            )
        ):
            _raise_report_invalid()
        object.__setattr__(self, "transitions", transitions)
        object.__setattr__(self, "events", events)


@dataclass(frozen=True, slots=True)
class MainForceMirrorDiagnosticSequenceProfileSection:
    profile_id: str
    peak_then_decay_sample_count: int
    long_sample_count: int
    short_sample_count: int
    product_count: int
    year_count: int
    top_product_share: Decimal
    median_delay_bars: Decimal | None
    h3_reversal_hit_rate: Decimal | None
    h5_reversal_hit_rate: Decimal | None
    yearly_median_reversal_min: Decimal | None
    side_median_reversal_min: Decimal | None
    breakdowns: tuple[MainForceMirrorDiagnosticSequenceBreakdown, ...]

    def __post_init__(self) -> None:
        counts = (
            self.peak_then_decay_sample_count,
            self.long_sample_count,
            self.short_sample_count,
            self.product_count,
            self.year_count,
        )
        metrics = (
            self.median_delay_bars,
            self.h3_reversal_hit_rate,
            self.h5_reversal_hit_rate,
            self.yearly_median_reversal_min,
            self.side_median_reversal_min,
        )
        breakdowns = _require_breakdowns(
            self.breakdowns,
            MainForceMirrorDiagnosticSequenceBreakdown,
        )
        if (
            self.profile_id not in _PROFILES
            or any(not _nonnegative_int(value) for value in counts)
            or self.long_sample_count + self.short_sample_count
            != self.peak_then_decay_sample_count
            or self.product_count > 60
            or self.year_count > 4
            or not _rate(self.top_product_share)
            or breakdowns[0].kept_episode_count
            != self.peak_then_decay_sample_count
        ):
            _raise_report_invalid()
        if self.peak_then_decay_sample_count == 0:
            if any(value is not None for value in metrics):
                _raise_report_invalid()
        elif (
            self.product_count == 0
            or self.year_count == 0
            or not _nonnegative_decimal(self.median_delay_bars)
            or not _rate(self.h3_reversal_hit_rate)
            or not _rate(self.h5_reversal_hit_rate)
            or not _finite_decimal(self.yearly_median_reversal_min)
            or not _finite_decimal(self.side_median_reversal_min)
        ):
            _raise_report_invalid()
        object.__setattr__(self, "breakdowns", breakdowns)


@dataclass(frozen=True, slots=True)
class MainForceMirrorDiagnosticSequenceSection:
    profiles: tuple[MainForceMirrorDiagnosticSequenceProfileSection, ...]

    def __post_init__(self) -> None:
        profiles = tuple(self.profiles)
        if (
            tuple(item.profile_id for item in profiles) != _PROFILES
            or any(
                not isinstance(item, MainForceMirrorDiagnosticSequenceProfileSection)
                for item in profiles
            )
        ):
            _raise_report_invalid()
        object.__setattr__(self, "profiles", profiles)


@dataclass(frozen=True, slots=True)
class MainForceMirrorDiagnosticScoreLatchBreakdown:
    key: MainForceMirrorDiagnosticBreakdownKey
    caution_ready_bar_count: int
    score_not_candidate_count: int
    long_only_candidate_count: int
    short_only_candidate_count: int
    dual_candidate_conflict_count: int
    high_score_unique_bar_count: int
    armed_candidate_count: int
    unarmed_candidate_suppressed_count: int
    long_caution_count: int
    short_caution_count: int
    caution_count: int
    long_rearm_count: int
    short_rearm_count: int

    def __post_init__(self) -> None:
        counts = tuple(
            getattr(self, field)
            for field in self.__dataclass_fields__
            if field != "key"
        )
        single_candidate_count = (
            self.long_only_candidate_count + self.short_only_candidate_count
        )
        if (
            not isinstance(self.key, MainForceMirrorDiagnosticBreakdownKey)
            or any(not _nonnegative_int(value) for value in counts)
            or self.score_not_candidate_count
            + single_candidate_count
            + self.dual_candidate_conflict_count
            != self.caution_ready_bar_count
            or single_candidate_count + self.dual_candidate_conflict_count
            != self.high_score_unique_bar_count
            or self.armed_candidate_count
            + self.unarmed_candidate_suppressed_count
            != single_candidate_count
            or self.long_caution_count + self.short_caution_count
            != self.caution_count
            or self.caution_count != self.armed_candidate_count
            or self.long_rearm_count > self.caution_ready_bar_count
            or self.short_rearm_count > self.caution_ready_bar_count
        ):
            _raise_report_invalid()


@dataclass(frozen=True, slots=True)
class MainForceMirrorDiagnosticFunnelSection:
    evaluable_bar_count: int
    high_score_bar_count: int
    conflict_bar_count: int
    armed_bar_count: int
    caution_episode_count: int
    latched_episode_count: int
    suppression_count: int
    breakdowns: tuple[MainForceMirrorDiagnosticScoreLatchBreakdown, ...]

    def __post_init__(self) -> None:
        counts = (
            self.evaluable_bar_count,
            self.high_score_bar_count,
            self.conflict_bar_count,
            self.armed_bar_count,
            self.caution_episode_count,
            self.latched_episode_count,
            self.suppression_count,
        )
        breakdowns = _require_breakdowns(
            self.breakdowns,
            MainForceMirrorDiagnosticScoreLatchBreakdown,
        )
        global_breakdown = breakdowns[0]
        if (
            any(not _nonnegative_int(value) for value in counts)
            or any(value > self.evaluable_bar_count for value in counts[1:])
            or self.latched_episode_count > self.caution_episode_count
            or self.latched_episode_count != self.caution_episode_count
            or (
                global_breakdown.caution_ready_bar_count,
                global_breakdown.high_score_unique_bar_count,
                global_breakdown.dual_candidate_conflict_count,
                global_breakdown.armed_candidate_count,
                global_breakdown.caution_count,
                global_breakdown.unarmed_candidate_suppressed_count,
            )
            != (
                self.evaluable_bar_count,
                self.high_score_bar_count,
                self.conflict_bar_count,
                self.armed_bar_count,
                self.caution_episode_count,
                self.suppression_count,
            )
        ):
            _raise_report_invalid()
        object.__setattr__(self, "breakdowns", breakdowns)


@dataclass(frozen=True, slots=True)
class MainForceMirrorDiagnosticModelFoldSection:
    fold: int
    fit_since: date
    fit_through: date
    evaluate_since: date
    evaluate_through: date
    fit_binary_count: int
    fit_negative_count: int
    fit_positive_count: int
    evaluate_binary_count: int
    evaluate_negative_count: int
    evaluate_positive_count: int
    evaluate_long_count: int
    evaluate_short_count: int
    evaluate_product_count: int
    bootstrap_valid_count: int
    score_auc: Decimal
    ridge_auc: Decimal
    current_tree_auc: Decimal
    full_tree_auc: Decimal
    ridge_score_delta: Decimal
    ridge_score_ci_lower: Decimal
    full_tree_ridge_delta: Decimal
    full_tree_ridge_ci_lower: Decimal
    full_tree_current_tree_delta: Decimal
    full_tree_current_tree_ci_lower: Decimal
    long_auc: Decimal
    short_auc: Decimal
    long_point_delta: Decimal
    short_point_delta: Decimal

    def __post_init__(self) -> None:
        counts = (
            self.fit_binary_count,
            self.fit_negative_count,
            self.fit_positive_count,
            self.evaluate_binary_count,
            self.evaluate_negative_count,
            self.evaluate_positive_count,
            self.evaluate_long_count,
            self.evaluate_short_count,
            self.evaluate_product_count,
            self.bootstrap_valid_count,
        )
        aucs = (
            self.score_auc,
            self.ridge_auc,
            self.current_tree_auc,
            self.full_tree_auc,
            self.long_auc,
            self.short_auc,
        )
        deltas = (
            self.ridge_score_delta,
            self.ridge_score_ci_lower,
            self.full_tree_ridge_delta,
            self.full_tree_ridge_ci_lower,
            self.full_tree_current_tree_delta,
            self.full_tree_current_tree_ci_lower,
            self.long_point_delta,
            self.short_point_delta,
        )
        if (
            self.fold not in (1, 2)
            or any(not _nonnegative_int(value) for value in counts)
            or self.fit_negative_count + self.fit_positive_count != self.fit_binary_count
            or self.evaluate_negative_count + self.evaluate_positive_count
            != self.evaluate_binary_count
            or self.evaluate_long_count + self.evaluate_short_count
            != self.evaluate_binary_count
            or self.evaluate_product_count > 60
            or self.bootstrap_valid_count > 2000
            or any(not _rate(value) for value in aucs)
            or any(not _finite_decimal(value) for value in deltas)
        ):
            _raise_report_invalid()


@dataclass(frozen=True, slots=True)
class MainForceMirrorDiagnosticModelBreakdown:
    key: MainForceMirrorDiagnosticBreakdownKey
    sample_count: int
    score_auc: Decimal | None
    ridge_auc: Decimal | None
    current_tree_auc: Decimal | None
    full_tree_auc: Decimal | None

    def __post_init__(self) -> None:
        metrics = (
            self.score_auc,
            self.ridge_auc,
            self.current_tree_auc,
            self.full_tree_auc,
        )
        if (
            not isinstance(self.key, MainForceMirrorDiagnosticBreakdownKey)
            or not _nonnegative_int(self.sample_count)
            or (
                self.sample_count == 0
                and any(metric is not None for metric in metrics)
            )
            or (
                self.sample_count > 0
                and any(not _rate(metric) for metric in metrics)
            )
        ):
            _raise_report_invalid()


@dataclass(frozen=True, slots=True)
class MainForceMirrorDiagnosticModelSection:
    folds: tuple[MainForceMirrorDiagnosticModelFoldSection, ...]
    breakdowns: tuple[MainForceMirrorDiagnosticModelBreakdown, ...]

    def __post_init__(self) -> None:
        folds = tuple(self.folds)
        breakdowns = _require_breakdowns(
            self.breakdowns,
            MainForceMirrorDiagnosticModelBreakdown,
        )
        if (
            len(folds) != 2
            or any(
                not isinstance(item, MainForceMirrorDiagnosticModelFoldSection)
                for item in folds
            )
            or tuple(item.fold for item in folds) != (1, 2)
            or tuple(
                (
                    item.fit_since,
                    item.fit_through,
                    item.evaluate_since,
                    item.evaluate_through,
                )
                for item in folds
            )
            != _FOLD_WINDOWS
        ):
            _raise_report_invalid()
        object.__setattr__(self, "folds", folds)
        object.__setattr__(self, "breakdowns", breakdowns)


@dataclass(frozen=True, slots=True)
class MainForceMirrorDiagnosticMemberSection:
    unique_earliest_count: int
    eligible_count: int
    t_minus_1_coverage: Decimal
    product_count: int
    causal_violation_count: int
    identity_violation_count: int
    member_model_present: bool

    def __post_init__(self) -> None:
        counts = (
            self.unique_earliest_count,
            self.eligible_count,
            self.product_count,
            self.causal_violation_count,
            self.identity_violation_count,
        )
        if any(not _nonnegative_int(value) for value in counts):
            _raise_report_invalid()
        expected_coverage = (
            Decimal(0)
            if self.unique_earliest_count == 0
            else Decimal(self.eligible_count) / Decimal(self.unique_earliest_count)
        )
        if (
            self.eligible_count > self.unique_earliest_count
            or self.t_minus_1_coverage != expected_coverage
            or not _rate(expected_coverage)
            or self.product_count > 60
            or self.member_model_present is not False
        ):
            _raise_report_invalid()


@dataclass(frozen=True, slots=True)
class MainForceMirrorDiagnosticReport:
    schema_version: int
    protocol_id: str
    model_subprotocol: str
    research_only: bool
    readonly: bool
    validation: MainForceMirrorDiagnosticValidationMetadata
    product_rows: tuple[MainForceMirrorDiagnosticProductRow, ...]
    label: MainForceMirrorDiagnosticLabelSection
    sequence: MainForceMirrorDiagnosticSequenceSection
    funnel: MainForceMirrorDiagnosticFunnelSection
    model: MainForceMirrorDiagnosticModelSection
    member: MainForceMirrorDiagnosticMemberSection
    quality_flags: tuple[str, ...]
    gate: MainForceMirrorDiagnosticGate
    gate_reasons: tuple[MainForceMirrorDiagnosticGateReason, ...]

    def __post_init__(self) -> None:
        rows = tuple(self.product_rows)
        flags = tuple(self.quality_flags)
        try:
            gate = MainForceMirrorDiagnosticGate(self.gate)
            reasons = tuple(MainForceMirrorDiagnosticGateReason(item) for item in self.gate_reasons)
        except (TypeError, ValueError):
            _raise_report_invalid()
        expected_reasons = tuple(
            reason for reason in MainForceMirrorDiagnosticGateReason if reason in reasons
        )
        available_count = sum(
            isinstance(row, MainForceMirrorDiagnosticAvailableProductRow) for row in rows
        )
        if (
            type(self.schema_version) is not int
            or self.schema_version != 1
            or self.protocol_id != _PROTOCOL_ID
            or self.model_subprotocol != _MODEL_SUBPROTOCOL
            or self.research_only is not True
            or self.readonly is not True
            or not isinstance(self.validation, MainForceMirrorDiagnosticValidationMetadata)
            or tuple(row.symbol for row in rows) != _PRODUCTS
            or any(
                type(row)
                not in (
                    MainForceMirrorDiagnosticAvailableProductRow,
                    MainForceMirrorDiagnosticUnavailableProductRow,
                )
                for row in rows
            )
            or self.validation.available_product_count != available_count
            or self.validation.unavailable_product_count != len(rows) - available_count
            or not isinstance(self.label, MainForceMirrorDiagnosticLabelSection)
            or not isinstance(self.sequence, MainForceMirrorDiagnosticSequenceSection)
            or not isinstance(self.funnel, MainForceMirrorDiagnosticFunnelSection)
            or not isinstance(self.model, MainForceMirrorDiagnosticModelSection)
            or not isinstance(self.member, MainForceMirrorDiagnosticMemberSection)
            or any(not _quality_flag(flag) for flag in flags)
            or len(set(flags)) != len(flags)
            or reasons != expected_reasons
            or len(set(reasons)) != len(reasons)
            or (gate is MainForceMirrorDiagnosticGate.STOP and not reasons)
            or (
                gate is MainForceMirrorDiagnosticGate.ALLOW_PHASE_FREEZE_DESIGN
                and bool(reasons)
            )
            or (
                (self.validation.unavailable_product_count > 0)
                != ("SOURCE_UNAVAILABLE_PRESENT" in flags)
            )
            or (
                (self.validation.unavailable_product_count > 0)
                != (
                    MainForceMirrorDiagnosticGateReason.SOURCE_UNAVAILABLE_PRESENT
                    in reasons
                )
            )
        ):
            _raise_report_invalid()
        object.__setattr__(self, "product_rows", rows)
        object.__setattr__(self, "quality_flags", flags)
        object.__setattr__(self, "gate", gate)
        object.__setattr__(self, "gate_reasons", reasons)


_BreakdownT = TypeVar("_BreakdownT")


def _expected_breakdown_keys() -> tuple[MainForceMirrorDiagnosticBreakdownKey, ...]:
    return (
        MainForceMirrorDiagnosticBreakdownKey(
            scope=MainForceMirrorDiagnosticBreakdownScope.GLOBAL,
        ),
        *(
            MainForceMirrorDiagnosticBreakdownKey(
                scope=MainForceMirrorDiagnosticBreakdownScope.PRODUCT,
                product=product,
            )
            for product in _PRODUCTS
        ),
        *(
            MainForceMirrorDiagnosticBreakdownKey(
                scope=MainForceMirrorDiagnosticBreakdownScope.YEAR,
                year=year,
            )
            for year in (2023, 2024, 2025, 2026)
        ),
        *(
            MainForceMirrorDiagnosticBreakdownKey(
                scope=MainForceMirrorDiagnosticBreakdownScope.SIDE,
                side=side,
            )
            for side in MainForceMirrorDiagnosticSide
        ),
        *(
            MainForceMirrorDiagnosticBreakdownKey(
                scope=MainForceMirrorDiagnosticBreakdownScope.FOLD,
                fold=fold,
            )
            for fold in (1, 2)
        ),
    )


def _require_breakdowns(
    value: tuple[_BreakdownT, ...],
    item_type: type[_BreakdownT],
) -> tuple[_BreakdownT, ...]:
    items = tuple(value)
    if (
        any(not isinstance(item, item_type) for item in items)
        or tuple(getattr(item, "key", None) for item in items)
        != _expected_breakdown_keys()
    ):
        _raise_report_invalid()
    return items


def _nonnegative_int(value: object) -> bool:
    return type(value) is int and value >= 0


def _positive_int(value: object) -> bool:
    return type(value) is int and value > 0


def _finite_decimal(value: object) -> TypeGuard[Decimal]:
    return type(value) is Decimal and value.is_finite()


def _nonnegative_decimal(value: object) -> bool:
    return _finite_decimal(value) and value >= 0


def _rate(value: object) -> bool:
    return _finite_decimal(value) and Decimal(0) <= value <= Decimal(1)


def _quality_flag(value: object) -> bool:
    return (
        type(value) is str
        and bool(value)
        and value == value.upper()
        and all(character.isalnum() or character == "_" for character in value)
    )


def _raise_report_invalid() -> Never:
    raise MainForceMirrorDiagnosticReportError()
