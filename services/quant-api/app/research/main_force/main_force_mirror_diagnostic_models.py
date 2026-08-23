"""Pure deterministic models and Gate for Main Force Mirror diagnostic Phase A."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from math import isfinite
from types import MappingProxyType
from collections.abc import Mapping
from typing import Any, cast

import numpy as np

from app.research.main_force.main_force_mirror_diagnostic import (
    MainForceMirrorDiagnosticGate,
    MainForceMirrorDiagnosticGateReason,
    MainForceMirrorDiagnosticBreakdownKey,
    MainForceMirrorDiagnosticBreakdownScope,
    MainForceMirrorDiagnosticLabelSection,
    MainForceMirrorDiagnosticSide,
    MainForceMirrorDiagnosticUnavailableReason,
    MainForceMirrorDiagnosticMemberSection,
    MainForceMirrorDiagnosticModelSection,
    MainForceMirrorDiagnosticModelFoldSection,
    MainForceMirrorDiagnosticModelBreakdown,
    MainForceMirrorDiagnosticSequenceSection,
    MainForceMirrorDiagnosticValidationMetadata,
    _expected_breakdown_keys,
)
from app.research.main_force.main_force_mirror_diagnostic_analysis import (
    MainForceMirrorDiagnosticFoldLabelOutcome,
    MainForceMirrorDiagnosticLabelAuditResult,
    MainForceMirrorDiagnosticLabelEpisode,
    MainForceMirrorDiagnosticLabelOutcome,
    MainForceMirrorDiagnosticProductInput,
    MainForceMirrorDiagnosticSequenceFactSet,
    _validate_product_input,
)
from app.research.main_force.main_force_mirror_v2_research_service import (
    MainForceMirrorV2SequenceFact,
)
from app.research.main_force.main_force_mirror_diagnostic_policy import (
    MainForceMirrorDiagnosticProtocol,
    require_exact_main_force_mirror_diagnostic_protocol,
)


CURRENT_FEATURE_NAMES = (
    "side_caution_score",
    "opposite_caution_score",
    "side_aligned_direction",
    "side_aligned_price_impulse",
    "side_aligned_clv",
    "volume_ratio",
    "oi_impulse",
    "side_range_extremity",
    "side_aligned_instant_pressure",
    "side_aligned_accumulated_pressure",
    "side_open_pressure_ratio",
    "side_break_distance_atr",
    "side_rejection_wick_ratio",
    "atr_close_ratio",
    "side_range_extreme_component",
    "side_liquidation_component",
    "side_open_pressure_divergence_component",
    "side_volume_rejection_component",
    "state_long_build",
    "state_short_build",
    "state_long_liquidation",
    "state_short_cover",
    "state_turnover",
)
SEQUENCE_FEATURE_NAMES = (
    "active_peak_present",
    "active_peak_same_side",
    "bars_since_active_peak",
    "decay_ratio",
    "side_aligned_active_peak_instant_pressure",
    "side_aligned_active_peak_accumulated_pressure",
    "decay_seen",
    "liquidation_seen",
    "opposite_build_seen",
    "accumulated_reversal_seen",
)
FEATURE_NAMES = CURRENT_FEATURE_NAMES + SEQUENCE_FEATURE_NAMES
_FOLD_WINDOWS = (
    (date(2023, 1, 1), date(2024, 12, 31), date(2025, 1, 1), date(2025, 12, 31)),
    (date(2023, 1, 1), date(2025, 12, 31), date(2026, 1, 1), date(2026, 8, 18)),
)


@dataclass(frozen=True, slots=True)
class MainForceMirrorDiagnosticFeatureRow:
    symbol: str
    physical_contract: str
    anchor_trading_day: date
    side: MainForceMirrorDiagnosticSide
    values: tuple[float, ...]


@dataclass(frozen=True, slots=True)
class MainForceMirrorDiagnosticModelSample:
    symbol: str
    physical_contract: str
    anchor_trading_day: date
    side: MainForceMirrorDiagnosticSide
    target: int
    features: tuple[float, ...]


@dataclass(frozen=True, slots=True)
class MainForceMirrorDiagnosticFoldDataset:
    fold: int
    fit: tuple[MainForceMirrorDiagnosticModelSample, ...]
    evaluate: tuple[MainForceMirrorDiagnosticModelSample, ...]


@dataclass(frozen=True, slots=True)
class MainForceMirrorDiagnosticFeatureUnavailable:
    symbol: str
    anchor_index: int
    reason: MainForceMirrorDiagnosticUnavailableReason


@dataclass(frozen=True, slots=True)
class MainForceMirrorDiagnosticFoldDatasets:
    folds: tuple[MainForceMirrorDiagnosticFoldDataset, ...]
    unavailable_episodes: tuple[MainForceMirrorDiagnosticFeatureUnavailable, ...]


@dataclass(frozen=True, slots=True)
class MainForceMirrorDiagnosticStandardizer:
    mean: tuple[float, ...]
    std: tuple[float, ...]


@dataclass(frozen=True, slots=True)
class MainForceMirrorDiagnosticRidgeModel:
    standardizer: MainForceMirrorDiagnosticStandardizer
    intercept: float
    coefficients: tuple[float, ...]
    iterations: int
    step_linf: float


@dataclass(frozen=True, slots=True)
class MainForceMirrorDiagnosticRidgeFit:
    model: MainForceMirrorDiagnosticRidgeModel | None
    unavailable_reason: MainForceMirrorDiagnosticUnavailableReason | None


@dataclass(frozen=True, slots=True)
class MainForceMirrorDiagnosticCartNode:
    probability: float
    feature_index: int | None = None
    threshold: float | None = None
    left: MainForceMirrorDiagnosticCartNode | None = None
    right: MainForceMirrorDiagnosticCartNode | None = None


@dataclass(frozen=True, slots=True)
class MainForceMirrorDiagnosticCartModel:
    standardizer: MainForceMirrorDiagnosticStandardizer
    feature_count: int
    root: MainForceMirrorDiagnosticCartNode


@dataclass(frozen=True, slots=True)
class MainForceMirrorDiagnosticCartFit:
    model: MainForceMirrorDiagnosticCartModel | None
    unavailable_reason: MainForceMirrorDiagnosticUnavailableReason | None


@dataclass(frozen=True, slots=True)
class MainForceMirrorDiagnosticBootstrapResult:
    valid_count: int
    point_deltas: Mapping[tuple[str, str], float]
    intervals: Mapping[tuple[str, str], tuple[float, float] | None]


@dataclass(frozen=True, slots=True)
class MainForceMirrorDiagnosticMemberObservation:
    symbol: str
    physical_contract: str
    anchor_trading_day: date
    anchor_bar_end: datetime
    expected_prior_trading_day: date
    expected_dataset_id: str
    available: bool
    observed_dataset_id: str | None
    observed_trade_date: date | None
    observed_symbol: str | None
    observed_physical_contract: str | None
    observed_rank: int | None

    def __post_init__(self) -> None:
        if (
            not self.symbol
            or self.symbol != self.symbol.lower()
            or not self.physical_contract
            or not isinstance(self.anchor_trading_day, date)
            or not isinstance(self.anchor_bar_end, datetime)
            or self.anchor_bar_end.tzinfo is None
            or not isinstance(self.expected_prior_trading_day, date)
            or self.expected_prior_trading_day >= self.anchor_trading_day
            or not self.expected_dataset_id
            or type(self.available) is not bool
        ):
            raise ValueError("MFM_DIAGNOSTIC_ANALYSIS_INVALID")


@dataclass(frozen=True, slots=True)
class MainForceMirrorDiagnosticMemberUnavailable:
    symbol: str
    physical_contract: str
    anchor_trading_day: date
    reason: MainForceMirrorDiagnosticUnavailableReason


@dataclass(frozen=True, slots=True)
class MainForceMirrorDiagnosticMemberFeasibilityResult:
    section: MainForceMirrorDiagnosticMemberSection
    unavailable: tuple[MainForceMirrorDiagnosticMemberUnavailable, ...]


@dataclass(frozen=True, slots=True)
class MainForceMirrorDiagnosticGateDecision:
    gate: MainForceMirrorDiagnosticGate
    reasons: tuple[MainForceMirrorDiagnosticGateReason, ...]


@dataclass(frozen=True, slots=True)
class MainForceMirrorDiagnosticModelAuditResult:
    section: MainForceMirrorDiagnosticModelSection


@dataclass(frozen=True, slots=True)
class _EvaluatedFold:
    fold: int
    samples: tuple[MainForceMirrorDiagnosticModelSample, ...]
    predictions: Mapping[str, tuple[float, ...]] | None
    unavailable_reason: MainForceMirrorDiagnosticUnavailableReason | None


def _fold_segments_for_day(value: date) -> tuple[tuple[int, str], ...]:
    result: list[tuple[int, str]] = []
    for fold, window in enumerate(_FOLD_WINDOWS, 1):
        if window[0] <= value <= window[1]:
            result.append((fold, "fit"))
        elif window[2] <= value <= window[3]:
            result.append((fold, "evaluate"))
    return tuple(result)


def _validate_fold_outcomes(
    episode: MainForceMirrorDiagnosticLabelEpisode,
) -> None:
    if type(episode.fold_outcomes) is not tuple:
        raise ValueError("MFM_DIAGNOSTIC_ANALYSIS_INVALID")
    outcomes = episode.fold_outcomes
    if (
        any(
            type(item) is not MainForceMirrorDiagnosticFoldLabelOutcome
            for item in outcomes
        )
        or any(
            type(item.fold) is not int
            or item.fold not in (1, 2)
            or type(item.segment) is not str
            for item in outcomes
        )
        or tuple((item.fold, item.segment) for item in outcomes)
        != _fold_segments_for_day(episode.anchor_trading_day)
    ):
        raise ValueError("MFM_DIAGNOSTIC_ANALYSIS_INVALID")
    physical_binary = episode.binary_target
    if (
        type(physical_binary) is not int
        and physical_binary is not None
    ) or physical_binary not in (None, 0, 1) or (
        episode.first_touch_offset is not None
        and type(episode.first_touch_offset) is not int
    ):
        raise ValueError("MFM_DIAGNOSTIC_ANALYSIS_INVALID")
    expected_physical_outcome = (
        MainForceMirrorDiagnosticLabelOutcome.FAVORABLE_FIRST
        if physical_binary == 0
        else (
            MainForceMirrorDiagnosticLabelOutcome.ADVERSE_FIRST
            if physical_binary == 1
            else None
        )
    )
    if (
        expected_physical_outcome is not None
        and (
            episode.outcome is not expected_physical_outcome
            or type(episode.first_touch_offset) is not int
            or not 1 <= episode.first_touch_offset <= 10
        )
    ) or (
        expected_physical_outcome is None
        and episode.outcome
        in {
            MainForceMirrorDiagnosticLabelOutcome.ADVERSE_FIRST,
            MainForceMirrorDiagnosticLabelOutcome.FAVORABLE_FIRST,
        }
    ):
        raise ValueError("MFM_DIAGNOSTIC_ANALYSIS_INVALID")
    for outcome in outcomes:
        binary = outcome.binary_target
        if (
            type(outcome.eligible) is not bool
            or (type(binary) is not int and binary is not None)
            or binary not in (None, 0, 1)
            or (
                outcome.outcome is not None
                and not isinstance(
                    outcome.outcome, MainForceMirrorDiagnosticLabelOutcome
                )
            )
        ):
            raise ValueError("MFM_DIAGNOSTIC_ANALYSIS_INVALID")
        if outcome.outcome is MainForceMirrorDiagnosticLabelOutcome.SPLIT_BOUNDARY_CENSORED:
            valid = binary is None and outcome.eligible is False
        else:
            valid = (
                outcome.outcome is episode.outcome
                and binary == physical_binary
                and outcome.eligible is (binary in (0, 1))
            )
        if not valid:
            raise ValueError("MFM_DIAGNOSTIC_ANALYSIS_INVALID")


def _sequence_side(value: float | None) -> str:
    converted = _number(value)
    if converted is None or converted == 0:
        return "neutral"
    return "long" if converted > 0 else "short"


def _sequence_fact_matches_point(
    point: Any,
    fact: MainForceMirrorV2SequenceFact,
    index: int,
) -> bool:
    expected_accumulated = (
        point.accumulated_pressure
        if point.accumulated_ready
        and _number(point.accumulated_pressure) is not None
        else None
    )
    return bool(
        fact.index == index
        and fact.current_side == _sequence_side(point.instant_pressure)
        and fact.pressure_state == point.pressure_state
        and fact.instant_pressure == point.instant_pressure
        and fact.accumulated_pressure == expected_accumulated
    )


def _validate_sequence_fact_structure(
    fact: MainForceMirrorV2SequenceFact,
    expected_index: int,
) -> None:
    active_index = fact.active_peak_index
    installed_index = fact.installed_peak_index
    bars_since = fact.bars_since_active_peak
    if (
        type(fact.index) is not int
        or fact.index != expected_index
        or (active_index is not None and type(active_index) is not int)
        or (installed_index is not None and type(installed_index) is not int)
        or (bars_since is not None and type(bars_since) is not int)
        or (
            active_index is not None
            and (
                not 0 <= active_index < fact.index
                or bars_since != fact.index - active_index
                or bars_since <= 0
            )
        )
        or (active_index is None and bars_since is not None)
        or (installed_index is not None and installed_index != fact.index)
    ):
        raise ValueError("MFM_DIAGNOSTIC_ANALYSIS_INVALID")


def _validate_active_peak_reference(
    product: MainForceMirrorDiagnosticProductInput,
    facts: tuple[MainForceMirrorV2SequenceFact, ...],
    anchor: MainForceMirrorV2SequenceFact,
    physical_contract: str,
) -> None:
    active_index = anchor.active_peak_index
    if active_index is None:
        return
    source = facts[active_index]
    source_point = product.points[active_index]
    if (
        source_point.physical_contract != physical_contract
        or not _sequence_fact_matches_point(source_point, source, active_index)
        or source.installed_peak_index != active_index
        or source.installed_peak_side != anchor.active_peak_side
        or source.installed_peak_instant_pressure
        != anchor.active_peak_instant_pressure
        or source.installed_peak_accumulated_pressure
        != anchor.active_peak_accumulated_pressure
        or source.peak_seen is not True
    ):
        raise ValueError("MFM_DIAGNOSTIC_ANALYSIS_INVALID")


def _validate_feature_identity(
    product: MainForceMirrorDiagnosticProductInput,
    episode: MainForceMirrorDiagnosticLabelEpisode,
    balanced_sequence: MainForceMirrorV2SequenceFact,
) -> None:
    if (
        not isinstance(product, MainForceMirrorDiagnosticProductInput)
        or not isinstance(episode, MainForceMirrorDiagnosticLabelEpisode)
        or not isinstance(balanced_sequence, MainForceMirrorV2SequenceFact)
    ):
        raise ValueError("MFM_DIAGNOSTIC_ANALYSIS_INVALID")
    _validate_product_input(product)
    if (
        episode.symbol != product.symbol
        or type(episode.anchor_index) is not int
        or not 0 <= episode.anchor_index < len(product.bars)
        or not isinstance(episode.anchor_trading_day, date)
        or not isinstance(episode.side, MainForceMirrorDiagnosticSide)
        or type(episode.kept) is not bool
    ):
        raise ValueError("MFM_DIAGNOSTIC_ANALYSIS_INVALID")
    index = episode.anchor_index
    _validate_sequence_fact_structure(balanced_sequence, index)
    bar = product.bars[index]
    point = product.points[index]
    trace = product.trace[index]
    expected_caution = (
        "long_chase_caution"
        if episode.side is MainForceMirrorDiagnosticSide.LONG
        else "short_chase_caution"
    )
    if (
        bar.trading_day != episode.anchor_trading_day
        or point.trading_day != episode.anchor_trading_day
        or trace.trading_day != episode.anchor_trading_day
        or point.physical_contract != episode.physical_contract
        or trace.physical_contract != episode.physical_contract
        or point.caution != expected_caution
        or trace.trigger != expected_caution
        or point.caution_conflict
        or trace.conflict
        or not _sequence_fact_matches_point(point, balanced_sequence, index)
        or any(
            type(value) is not bool
            for value in (
                balanced_sequence.peak_seen,
                balanced_sequence.decay_seen,
                balanced_sequence.liquidation_seen,
                balanced_sequence.opposite_build_seen,
                balanced_sequence.accumulated_reversal_seen,
            )
        )
    ):
        raise ValueError("MFM_DIAGNOSTIC_ANALYSIS_INVALID")
    active_index = balanced_sequence.active_peak_index
    active_identity = (
        balanced_sequence.active_peak_side,
        balanced_sequence.active_peak_instant_pressure,
        balanced_sequence.active_peak_accumulated_pressure,
        balanced_sequence.bars_since_active_peak,
        balanced_sequence.decay_ratio,
    )
    if active_index is None:
        if any(value is not None for value in active_identity):
            raise ValueError("MFM_DIAGNOSTIC_ANALYSIS_INVALID")
    elif (
        type(active_index) is not int
        or not 0 <= active_index < index
        or balanced_sequence.active_peak_side not in ("long", "short")
        or type(balanced_sequence.bars_since_active_peak) is not int
        or balanced_sequence.bars_since_active_peak != index - active_index
        or balanced_sequence.bars_since_active_peak <= 0
    ):
        raise ValueError("MFM_DIAGNOSTIC_ANALYSIS_INVALID")
    _validate_fold_outcomes(episode)


def build_main_force_mirror_feature_row(
    product: MainForceMirrorDiagnosticProductInput,
    episode: MainForceMirrorDiagnosticLabelEpisode,
    balanced_sequence: MainForceMirrorV2SequenceFact,
) -> MainForceMirrorDiagnosticFeatureRow | None:
    """Build the frozen 33-feature row; expected missing evidence stays typed."""

    _validate_feature_identity(product, episode, balanced_sequence)
    if not episode.kept:
        raise ValueError("MFM_DIAGNOSTIC_ANALYSIS_INVALID")
    index = episode.anchor_index
    bar = product.bars[index]
    point = product.points[index]
    trace = product.trace[index]
    sign = 1.0 if episode.side is MainForceMirrorDiagnosticSide.LONG else -1.0
    is_long = sign > 0
    side_score = trace.long_score if is_long else trace.short_score
    opposite_score = trace.short_score if is_long else trace.long_score
    side_open = trace.long_open_pressure if is_long else trace.short_open_pressure
    prior_open = (
        trace.prior_long_open_pressure_max
        if is_long
        else trace.prior_short_open_pressure_max
    )
    atr = trace.atr14
    close = _number(bar.close)
    high = _number(bar.high)
    low = _number(bar.low)
    prior_high = trace.prior_high_max
    prior_low = trace.prior_low_min
    rejection = trace.upper_wick_ratio if is_long else trace.lower_wick_ratio
    current_numbers = _numbers(
        (
        side_score,
        opposite_score,
        trace.direction,
        trace.price_impulse,
        trace.clv,
        trace.volume_ratio,
        trace.oi_impulse,
        trace.range_position,
        trace.instant_pressure,
        trace.accumulated_pressure,
        side_open,
        prior_open,
        atr,
        close,
        high,
        low,
        prior_high,
        prior_low,
        rejection,
        )
    )
    if (
        trace.components is None
        or point.pressure_state
        not in {
            "long_build",
            "short_build",
            "long_liquidation",
            "short_cover",
            "turnover",
        }
        or current_numbers is None
    ):
        return None
    (
        side_score_value,
        opposite_score_value,
        direction_value,
        price_impulse_value,
        clv_value,
        volume_ratio_value,
        oi_impulse_value,
        range_position_value,
        instant_pressure_value,
        accumulated_pressure_value,
        side_open_value,
        prior_open_value,
        atr_value,
        close_value,
        high_value,
        low_value,
        prior_high_value,
        prior_low_value,
        rejection_value,
    ) = current_numbers
    if prior_open_value <= 0 or atr_value <= 0 or close_value <= 0:
        return None
    components = trace.components
    if is_long:
        side_components = (
            components.long_upper_extreme,
            components.long_short_cover_dominated,
            components.long_open_pressure_divergence,
            components.long_high_volume_exhaustion,
        )
        break_distance = (high_value - prior_high_value) / atr_value
        range_extremity = range_position_value
    else:
        side_components = (
            components.short_lower_extreme,
            components.short_long_liquidation_dominated,
            components.short_open_pressure_divergence,
            components.short_low_price_absorption,
        )
        break_distance = (prior_low_value - low_value) / atr_value
        range_extremity = 1.0 - range_position_value
    states = tuple(
        float(point.pressure_state == state)
        for state in (
            "long_build",
            "short_build",
            "long_liquidation",
            "short_cover",
            "turnover",
        )
    )
    current = (
        side_score_value,
        opposite_score_value,
        sign * direction_value,
        sign * price_impulse_value,
        sign * clv_value,
        volume_ratio_value,
        oi_impulse_value,
        range_extremity,
        sign * instant_pressure_value / 100.0,
        sign * accumulated_pressure_value / 100.0,
        side_open_value / prior_open_value,
        break_distance,
        rejection_value,
        atr_value / close_value,
        *(float(value) for value in side_components),
        *states,
    )
    if balanced_sequence.active_peak_index is None:
        sequence = (0.0,) * 10
    else:
        active_values = _numbers((
            balanced_sequence.active_peak_instant_pressure,
            balanced_sequence.active_peak_accumulated_pressure,
            balanced_sequence.bars_since_active_peak,
            balanced_sequence.decay_ratio,
        ))
        if (
            balanced_sequence.active_peak_side not in ("long", "short")
            or active_values is None
            or active_values[2] < 0
        ):
            return None
        sequence = (
            1.0,
            float(
                balanced_sequence.active_peak_side
                == ("long" if is_long else "short")
            ),
            active_values[2],
            active_values[3],
            sign * active_values[0] / 100.0,
            sign * active_values[1] / 100.0,
            float(balanced_sequence.decay_seen),
            float(balanced_sequence.liquidation_seen),
            float(balanced_sequence.opposite_build_seen),
            float(balanced_sequence.accumulated_reversal_seen),
        )
    values = (*current, *sequence)
    if len(values) != len(FEATURE_NAMES) or any(not isfinite(value) for value in values):
        return None
    return MainForceMirrorDiagnosticFeatureRow(
        symbol=episode.symbol,
        physical_contract=episode.physical_contract,
        anchor_trading_day=episode.anchor_trading_day,
        side=episode.side,
        values=values,
    )


def build_main_force_mirror_fold_datasets(
    products: tuple[MainForceMirrorDiagnosticProductInput, ...],
    labels: MainForceMirrorDiagnosticLabelAuditResult,
    balanced_fact_sets: tuple[MainForceMirrorDiagnosticSequenceFactSet, ...],
) -> MainForceMirrorDiagnosticFoldDatasets:
    """Build the two fixed fold views solely from Task 3 fold eligibility."""

    inputs = tuple(products)
    fact_sets = tuple(balanced_fact_sets)
    if (
        not isinstance(labels, MainForceMirrorDiagnosticLabelAuditResult)
        or any(
            not isinstance(item, MainForceMirrorDiagnosticProductInput)
            for item in inputs
        )
        or any(
            not isinstance(item, MainForceMirrorDiagnosticSequenceFactSet)
            or item.profile_id != "balanced"
            or type(item.facts) is not tuple
            for item in fact_sets
        )
        or any(
            not isinstance(item, MainForceMirrorDiagnosticLabelEpisode)
            for item in labels.episodes
        )
    ):
        raise ValueError("MFM_DIAGNOSTIC_ANALYSIS_INVALID")
    if labels.inputs != inputs:
        raise ValueError("MFM_DIAGNOSTIC_ANALYSIS_INVALID")
    product_by_symbol = {item.symbol: item for item in inputs}
    facts_by_symbol = {
        item.symbol: item.facts
        for item in fact_sets
    }
    if (
        len(product_by_symbol) != len(inputs)
        or len(facts_by_symbol) != len(inputs)
        or set(facts_by_symbol) != set(product_by_symbol)
        or any(
            len(facts_by_symbol[symbol]) != len(product.points)
            or any(
                not isinstance(fact, MainForceMirrorV2SequenceFact)
                or type(fact.index) is not int
                or fact.index != index
                for index, fact in enumerate(facts_by_symbol[symbol])
            )
            for symbol, product in product_by_symbol.items()
        )
    ):
        raise ValueError("MFM_DIAGNOSTIC_ANALYSIS_INVALID")
    for symbol in product_by_symbol:
        for index, fact in enumerate(facts_by_symbol[symbol]):
            _validate_sequence_fact_structure(fact, index)
    samples: dict[tuple[int, str], list[MainForceMirrorDiagnosticModelSample]] = {
        (fold, segment): []
        for fold in (1, 2)
        for segment in ("fit", "evaluate")
    }
    unavailable: list[MainForceMirrorDiagnosticFeatureUnavailable] = []
    for episode in labels.episodes:
        product = product_by_symbol.get(episode.symbol)
        if (
            product is None
            or type(episode.anchor_index) is not int
            or not 0 <= episode.anchor_index < len(product.points)
        ):
            raise ValueError("MFM_DIAGNOSTIC_ANALYSIS_INVALID")
        fact = facts_by_symbol[episode.symbol][episode.anchor_index]
        _validate_feature_identity(product, episode, fact)
        _validate_active_peak_reference(
            product,
            facts_by_symbol[episode.symbol],
            fact,
            episode.physical_contract,
        )
        if not episode.kept:
            continue
        row = build_main_force_mirror_feature_row(
            product,
            episode,
            fact,
        )
        eligible_outcomes = tuple(item for item in episode.fold_outcomes if item.eligible)
        if row is None:
            if eligible_outcomes:
                unavailable.append(
                    MainForceMirrorDiagnosticFeatureUnavailable(
                        symbol=episode.symbol,
                        anchor_index=episode.anchor_index,
                        reason=MainForceMirrorDiagnosticUnavailableReason.FEATURE_UNAVAILABLE,
                    )
                )
            continue
        for outcome in episode.fold_outcomes:
            if not outcome.eligible:
                if outcome.binary_target is not None:
                    raise ValueError("MFM_DIAGNOSTIC_ANALYSIS_INVALID")
                continue
            if outcome.binary_target not in (0, 1) or outcome.segment not in (
                "fit",
                "evaluate",
            ):
                raise ValueError("MFM_DIAGNOSTIC_ANALYSIS_INVALID")
            samples[(outcome.fold, outcome.segment)].append(
                MainForceMirrorDiagnosticModelSample(
                    symbol=row.symbol,
                    physical_contract=row.physical_contract,
                    anchor_trading_day=row.anchor_trading_day,
                    side=row.side,
                    target=outcome.binary_target,
                    features=row.values,
                )
            )
    return MainForceMirrorDiagnosticFoldDatasets(
        folds=tuple(
            MainForceMirrorDiagnosticFoldDataset(
                fold=fold,
                fit=tuple(samples[(fold, "fit")]),
                evaluate=tuple(samples[(fold, "evaluate")]),
            )
            for fold in (1, 2)
        ),
        unavailable_episodes=tuple(unavailable),
    )


def fit_main_force_mirror_standardizer(
    features: np.ndarray,
) -> MainForceMirrorDiagnosticStandardizer:
    values = _feature_matrix(features)
    if len(values) == 0 or not np.all(np.isfinite(values)):
        raise ValueError("MFM_DIAGNOSTIC_ANALYSIS_INVALID")
    mean = np.mean(values, axis=0)
    std = np.std(values, axis=0)
    std = np.where(std == 0.0, 1.0, std)
    if not np.all(np.isfinite(mean)) or not np.all(np.isfinite(std)):
        raise ValueError("MFM_DIAGNOSTIC_ANALYSIS_INVALID")
    return MainForceMirrorDiagnosticStandardizer(
        mean=tuple(float(value) for value in mean),
        std=tuple(float(value) for value in std),
    )


def transform_main_force_mirror_features(
    features: np.ndarray,
    standardizer: MainForceMirrorDiagnosticStandardizer,
) -> np.ndarray:
    values = _feature_matrix(features)
    mean = np.asarray(standardizer.mean, dtype=float)
    std = np.asarray(standardizer.std, dtype=float)
    if values.shape[1] != len(mean) or len(mean) != len(std):
        raise ValueError("MFM_DIAGNOSTIC_ANALYSIS_INVALID")
    return (values - mean) / std


def main_force_mirror_class_weights(targets: np.ndarray) -> np.ndarray:
    values = _target_vector(targets)
    negative = int(np.sum(values == 0.0))
    positive = int(np.sum(values == 1.0))
    if negative == 0 or positive == 0:
        raise ValueError("MFM_DIAGNOSTIC_ANALYSIS_INVALID")
    total = len(values)
    return np.where(
        values == 0.0,
        total / (2.0 * negative),
        total / (2.0 * positive),
    )


def fit_main_force_mirror_ridge(
    features: np.ndarray,
    targets: np.ndarray,
) -> MainForceMirrorDiagnosticRidgeFit:
    try:
        values = _feature_matrix(features)
        labels = _target_vector(targets)
    except ValueError:
        return MainForceMirrorDiagnosticRidgeFit(
            model=None,
            unavailable_reason=(
                MainForceMirrorDiagnosticUnavailableReason.MODEL_CONVERGENCE_FAILED
            ),
        )
    if len(values) != len(labels) or not np.all(np.isfinite(values)):
        return MainForceMirrorDiagnosticRidgeFit(
            model=None,
            unavailable_reason=(
                MainForceMirrorDiagnosticUnavailableReason.MODEL_CONVERGENCE_FAILED
            ),
        )
    if len(np.unique(labels)) != 2:
        return MainForceMirrorDiagnosticRidgeFit(
            model=None,
            unavailable_reason=(
                MainForceMirrorDiagnosticUnavailableReason.SPLIT_CLASS_UNAVAILABLE
            ),
        )
    try:
        standardizer = fit_main_force_mirror_standardizer(values)
        standardized = transform_main_force_mirror_features(values, standardizer)
        weights = main_force_mirror_class_weights(labels)
    except ValueError:
        return MainForceMirrorDiagnosticRidgeFit(
            model=None,
            unavailable_reason=(
                MainForceMirrorDiagnosticUnavailableReason.MODEL_CONVERGENCE_FAILED
            ),
        )
    design = np.column_stack((np.ones(len(standardized)), standardized))
    parameters = np.zeros(design.shape[1], dtype=float)
    last_step = float("inf")
    for iteration in range(1, 101):
        logits = design @ parameters
        probabilities = _sigmoid(logits)
        gradient = design.T @ (weights * (probabilities - labels))
        gradient[1:] += parameters[1:]
        curvature = weights * probabilities * (1.0 - probabilities)
        hessian = design.T @ (design * curvature[:, None])
        hessian[1:, 1:] += np.eye(design.shape[1] - 1)
        if not np.all(np.isfinite(gradient)) or not np.all(np.isfinite(hessian)):
            break
        try:
            step = np.linalg.solve(hessian, gradient)
        except np.linalg.LinAlgError:
            break
        if not np.all(np.isfinite(step)):
            break
        parameters -= step
        last_step = float(np.max(np.abs(step)))
        if last_step <= 1e-8:
            return MainForceMirrorDiagnosticRidgeFit(
                model=MainForceMirrorDiagnosticRidgeModel(
                    standardizer=standardizer,
                    intercept=float(parameters[0]),
                    coefficients=tuple(float(value) for value in parameters[1:]),
                    iterations=iteration,
                    step_linf=last_step,
                ),
                unavailable_reason=None,
            )
    return MainForceMirrorDiagnosticRidgeFit(
        model=None,
        unavailable_reason=(
            MainForceMirrorDiagnosticUnavailableReason.MODEL_CONVERGENCE_FAILED
        ),
    )


def predict_main_force_mirror_ridge(
    model: MainForceMirrorDiagnosticRidgeModel,
    features: np.ndarray,
) -> np.ndarray:
    values = transform_main_force_mirror_features(features, model.standardizer)
    logits = model.intercept + values @ np.asarray(model.coefficients, dtype=float)
    return _sigmoid(logits)


def fit_main_force_mirror_cart(
    features: np.ndarray,
    targets: np.ndarray,
    *,
    feature_count: int,
) -> MainForceMirrorDiagnosticCartFit:
    try:
        values = _feature_matrix(features)
        labels = _target_vector(targets)
    except ValueError:
        return MainForceMirrorDiagnosticCartFit(
            model=None,
            unavailable_reason=(
                MainForceMirrorDiagnosticUnavailableReason.MODEL_CONVERGENCE_FAILED
            ),
        )
    if (
        len(values) != len(labels)
        or type(feature_count) is not int
        or not 1 <= feature_count <= values.shape[1]
        or not np.all(np.isfinite(values))
    ):
        return MainForceMirrorDiagnosticCartFit(
            model=None,
            unavailable_reason=(
                MainForceMirrorDiagnosticUnavailableReason.MODEL_CONVERGENCE_FAILED
            ),
        )
    if len(np.unique(labels)) != 2:
        return MainForceMirrorDiagnosticCartFit(
            model=None,
            unavailable_reason=(
                MainForceMirrorDiagnosticUnavailableReason.SPLIT_CLASS_UNAVAILABLE
            ),
        )
    try:
        standardizer = fit_main_force_mirror_standardizer(values)
        standardized = transform_main_force_mirror_features(
            values, standardizer
        )[:, :feature_count]
        weights = main_force_mirror_class_weights(labels)
        thresholds = tuple(
            tuple(
                dict.fromkeys(
                    float(value)
                    for value in np.quantile(
                        standardized[:, feature],
                        (0.25, 0.50, 0.75),
                        method="linear",
                    )
                )
            )
            for feature in range(feature_count)
        )
        root = _build_cart_node(
            standardized,
            labels,
            weights,
            np.arange(len(labels)),
            thresholds,
            depth=0,
        )
    except (ValueError, FloatingPointError, OverflowError):
        return MainForceMirrorDiagnosticCartFit(
            model=None,
            unavailable_reason=(
                MainForceMirrorDiagnosticUnavailableReason.MODEL_CONVERGENCE_FAILED
            ),
        )
    return MainForceMirrorDiagnosticCartFit(
        model=MainForceMirrorDiagnosticCartModel(
            standardizer=standardizer,
            feature_count=feature_count,
            root=root,
        ),
        unavailable_reason=None,
    )


def predict_main_force_mirror_cart(
    model: MainForceMirrorDiagnosticCartModel,
    features: np.ndarray,
) -> np.ndarray:
    standardized = transform_main_force_mirror_features(
        features, model.standardizer
    )[:, : model.feature_count]
    return np.asarray(
        [_cart_probability(model.root, row) for row in standardized],
        dtype=float,
    )


def main_force_mirror_auc(
    targets: np.ndarray,
    predictions: np.ndarray,
) -> float | None:
    try:
        labels = _target_vector(targets)
    except ValueError:
        return None
    values = np.asarray(predictions, dtype=float)
    if (
        values.ndim != 1
        or len(values) != len(labels)
        or not np.all(np.isfinite(values))
    ):
        return None
    positive_count = int(np.sum(labels == 1.0))
    negative_count = len(labels) - positive_count
    if positive_count == 0 or negative_count == 0:
        return None
    order = np.argsort(values, kind="mergesort")
    ranks = np.empty(len(values), dtype=float)
    start = 0
    while start < len(values):
        end = start + 1
        while end < len(values) and values[order[end]] == values[order[start]]:
            end += 1
        average_rank = ((start + 1) + end) / 2.0
        ranks[order[start:end]] = average_rank
        start = end
    positive_rank_sum = float(np.sum(ranks[labels == 1.0]))
    return (
        positive_rank_sum - positive_count * (positive_count + 1) / 2.0
    ) / (positive_count * negative_count)


def bootstrap_main_force_mirror_auc_deltas(
    targets: np.ndarray,
    products: np.ndarray,
    predictions: Mapping[str, np.ndarray],
    comparisons: tuple[tuple[str, str], ...],
) -> MainForceMirrorDiagnosticBootstrapResult:
    labels = _target_vector(targets)
    product_values = np.asarray(products, dtype=object)
    prediction_values = {
        name: np.asarray(values, dtype=float)
        for name, values in predictions.items()
    }
    if (
        product_values.ndim != 1
        or len(product_values) != len(labels)
        or not prediction_values
        or any(
            values.ndim != 1
            or len(values) != len(labels)
            or not np.all(np.isfinite(values))
            for values in prediction_values.values()
        )
        or any(
            left not in prediction_values or right not in prediction_values
            for left, right in comparisons
        )
    ):
        raise ValueError("MFM_DIAGNOSTIC_ANALYSIS_INVALID")
    clusters = tuple(dict.fromkeys(product_values.tolist()))
    if not clusters:
        raise ValueError("MFM_DIAGNOSTIC_ANALYSIS_INVALID")
    cluster_indices = {
        cluster: np.flatnonzero(product_values == cluster)
        for cluster in clusters
    }
    point_aucs = {
        name: main_force_mirror_auc(labels, values)
        for name, values in prediction_values.items()
    }
    point_deltas: dict[tuple[str, str], float] = {}
    for comparison in comparisons:
        left_auc = point_aucs[comparison[0]]
        right_auc = point_aucs[comparison[1]]
        point_deltas[comparison] = (
            float("nan")
            if left_auc is None or right_auc is None
            else left_auc - right_auc
        )
    rng = np.random.default_rng(20260823)
    values_by_comparison: dict[tuple[str, str], list[float]] = {
        comparison: [] for comparison in comparisons
    }
    valid_count = 0
    for _ in range(2000):
        sampled = rng.choice(clusters, size=len(clusters), replace=True)
        indices = np.concatenate(tuple(cluster_indices[item] for item in sampled))
        replicate_aucs = {
            name: main_force_mirror_auc(labels[indices], values[indices])
            for name, values in prediction_values.items()
        }
        if any(
            replicate_aucs[left] is None or replicate_aucs[right] is None
            for left, right in comparisons
        ):
            continue
        valid_count += 1
        for comparison in comparisons:
            left, right = comparison
            left_auc = replicate_aucs[left]
            right_auc = replicate_aucs[right]
            assert left_auc is not None
            assert right_auc is not None
            values_by_comparison[comparison].append(
                left_auc - right_auc
            )
    intervals: dict[tuple[str, str], tuple[float, float] | None] = {}
    for comparison, values in values_by_comparison.items():
        if valid_count < 1900:
            intervals[comparison] = None
        else:
            lower, upper = np.quantile(
                np.asarray(values, dtype=float),
                (0.025, 0.975),
                method="linear",
            )
            intervals[comparison] = (float(lower), float(upper))
    return MainForceMirrorDiagnosticBootstrapResult(
        valid_count=valid_count,
        point_deltas=MappingProxyType(point_deltas),
        intervals=MappingProxyType(intervals),
    )


def audit_main_force_mirror_member_feasibility(
    observations: tuple[MainForceMirrorDiagnosticMemberObservation, ...],
) -> MainForceMirrorDiagnosticMemberFeasibilityResult:
    if type(observations) is not tuple:
        raise ValueError("MFM_DIAGNOSTIC_ANALYSIS_INVALID")
    values = observations
    for item in values:
        _validate_member_observation_structure(item)
    grouped: dict[
        tuple[str, str, date], list[MainForceMirrorDiagnosticMemberObservation]
    ] = {}
    for item in values:
        key = (item.symbol, item.physical_contract, item.anchor_trading_day)
        grouped.setdefault(key, []).append(item)
    earliest: dict[
        tuple[str, str, date], MainForceMirrorDiagnosticMemberObservation
    ] = {}
    for key in sorted(grouped):
        group = grouped[key]
        earliest_end = min(item.anchor_bar_end for item in group)
        tied = tuple(
            item for item in group if item.anchor_bar_end == earliest_end
        )
        first = tied[0]
        if any(item != first for item in tied[1:]):
            raise ValueError("MFM_DIAGNOSTIC_ANALYSIS_INVALID")
        earliest[key] = first
    eligible_products: set[str] = set()
    eligible_count = 0
    causal_violations = 0
    identity_violations = 0
    unavailable: list[MainForceMirrorDiagnosticMemberUnavailable] = []
    for item in earliest.values():
        reason: MainForceMirrorDiagnosticUnavailableReason | None = None
        if not item.available:
            reason = MainForceMirrorDiagnosticUnavailableReason.MEMBER_DATASET_UNAVAILABLE
        elif any(
            value is None
            for value in (
                item.observed_dataset_id,
                item.observed_trade_date,
                item.observed_symbol,
                item.observed_physical_contract,
                item.observed_rank,
            )
        ):
            reason = MainForceMirrorDiagnosticUnavailableReason.MEMBER_T_MINUS_1_UNAVAILABLE
        else:
            identity_invalid = (
                item.observed_dataset_id != item.expected_dataset_id
                or item.observed_symbol != item.symbol
                or item.observed_physical_contract != item.physical_contract
                or type(item.observed_rank) is not int
                or item.observed_rank != 1
            )
            causal_invalid = (
                item.observed_trade_date != item.expected_prior_trading_day
            )
            identity_violations += int(identity_invalid)
            causal_violations += int(causal_invalid)
            if identity_invalid:
                reason = MainForceMirrorDiagnosticUnavailableReason.MEMBER_IDENTITY_CONFLICT
            elif causal_invalid:
                reason = MainForceMirrorDiagnosticUnavailableReason.MEMBER_T_MINUS_1_UNAVAILABLE
        if reason is None:
            eligible_count += 1
            eligible_products.add(item.symbol)
        else:
            unavailable.append(
                MainForceMirrorDiagnosticMemberUnavailable(
                    symbol=item.symbol,
                    physical_contract=item.physical_contract,
                    anchor_trading_day=item.anchor_trading_day,
                    reason=reason,
                )
            )
    unique_count = len(earliest)
    return MainForceMirrorDiagnosticMemberFeasibilityResult(
        section=MainForceMirrorDiagnosticMemberSection(
            unique_earliest_count=unique_count,
            eligible_count=eligible_count,
            t_minus_1_coverage=(
                Decimal(0)
                if unique_count == 0
                else Decimal(eligible_count) / Decimal(unique_count)
            ),
            product_count=len(eligible_products),
            causal_violation_count=causal_violations,
            identity_violation_count=identity_violations,
            member_model_present=False,
        ),
        unavailable=tuple(unavailable),
    )


def _validate_member_observation_structure(item: object) -> None:
    if not isinstance(item, MainForceMirrorDiagnosticMemberObservation):
        raise ValueError("MFM_DIAGNOSTIC_ANALYSIS_INVALID")
    observed_strings = (
        item.observed_dataset_id,
        item.observed_symbol,
        item.observed_physical_contract,
    )
    if (
        type(item.symbol) is not str
        or not item.symbol
        or type(item.physical_contract) is not str
        or not item.physical_contract
        or type(item.anchor_trading_day) is not date
        or type(item.anchor_bar_end) is not datetime
        or item.anchor_bar_end.tzinfo is None
        or type(item.expected_prior_trading_day) is not date
        or type(item.expected_dataset_id) is not str
        or not item.expected_dataset_id
        or type(item.available) is not bool
        or any(value is not None and type(value) is not str for value in observed_strings)
        or (
            item.observed_trade_date is not None
            and type(item.observed_trade_date) is not date
        )
        or (
            item.observed_rank is not None
            and type(item.observed_rank) not in (int, bool)
        )
    ):
        raise ValueError("MFM_DIAGNOSTIC_ANALYSIS_INVALID")


def evaluate_main_force_mirror_diagnostic_gate(
    protocol: MainForceMirrorDiagnosticProtocol,
    validation: MainForceMirrorDiagnosticValidationMetadata,
    label: MainForceMirrorDiagnosticLabelSection,
    sequence: MainForceMirrorDiagnosticSequenceSection,
    model: MainForceMirrorDiagnosticModelSection,
    member: MainForceMirrorDiagnosticMemberSection,
) -> MainForceMirrorDiagnosticGateDecision:
    """Evaluate every frozen check and retain all normal insufficiency reasons."""

    exact = require_exact_main_force_mirror_diagnostic_protocol(protocol)
    if (
        not isinstance(validation, MainForceMirrorDiagnosticValidationMetadata)
        or not isinstance(label, MainForceMirrorDiagnosticLabelSection)
        or not isinstance(sequence, MainForceMirrorDiagnosticSequenceSection)
        or not isinstance(model, MainForceMirrorDiagnosticModelSection)
        or not isinstance(member, MainForceMirrorDiagnosticMemberSection)
    ):
        raise ValueError("MFM_DIAGNOSTIC_ANALYSIS_INVALID")
    failed: set[MainForceMirrorDiagnosticGateReason] = set()
    if validation.unavailable_product_count > 0:
        failed.add(MainForceMirrorDiagnosticGateReason.SOURCE_UNAVAILABLE_PRESENT)
    if validation.available_product_count < exact.available_products_floor or any(
        fold.fit_binary_count < exact.fit_binary_floor
        or fold.fit_negative_count < exact.fit_each_class_floor
        or fold.fit_positive_count < exact.fit_each_class_floor
        or fold.evaluate_binary_count < exact.evaluate_binary_floor
        or fold.evaluate_negative_count < exact.evaluate_each_class_floor
        or fold.evaluate_positive_count < exact.evaluate_each_class_floor
        or fold.evaluate_long_count < exact.evaluate_each_side_floor
        or fold.evaluate_short_count < exact.evaluate_each_side_floor
        or fold.evaluate_product_count < exact.evaluate_products_floor
        for fold in model.folds
    ):
        failed.add(MainForceMirrorDiagnosticGateReason.SAMPLE_FLOOR_FAILED)
    fold_label_rows = tuple(
        row
        for row in label.breakdowns
        if row.key.scope is MainForceMirrorDiagnosticBreakdownScope.FOLD
    )
    if label.resolved_coverage < exact.resolved_coverage_floor or any(
        (
            Decimal(0)
            if row.kept_sample_count == 0
            else Decimal(row.binary_evaluable_count)
            / Decimal(row.kept_sample_count)
        )
        < exact.resolved_coverage_floor
        for row in fold_label_rows
    ):
        failed.add(
            MainForceMirrorDiagnosticGateReason.BINARY_COVERAGE_INSUFFICIENT
        )
    if label.ambiguous_rate > exact.ambiguous_rate_maximum or any(
        (
            Decimal(0)
            if row.kept_sample_count == 0
            else Decimal(row.ambiguous_count) / Decimal(row.kept_sample_count)
        )
        > exact.ambiguous_rate_maximum
        for row in fold_label_rows
    ):
        failed.add(MainForceMirrorDiagnosticGateReason.AMBIGUOUS_RATE_EXCEEDED)
    stable_profiles = tuple(
        profile
        for profile in sequence.profiles
        if _sequence_profile_stable(exact, profile)
    )
    if (
        (exact.sequence_balanced_required and not any(
            item.profile_id == "balanced" for item in stable_profiles
        ))
        or len(stable_profiles) < exact.sequence_required_profiles
    ):
        failed.add(MainForceMirrorDiagnosticGateReason.SEQUENCE_UNSTABLE)
    for fold in model.folds:
        core_metrics = (
            fold.score_auc,
            fold.ridge_auc,
            fold.current_tree_auc,
            fold.full_tree_auc,
            fold.ridge_score_delta,
            fold.ridge_score_ci_lower,
            fold.full_tree_ridge_delta,
            fold.full_tree_ridge_ci_lower,
            fold.full_tree_current_tree_delta,
            fold.full_tree_current_tree_ci_lower,
        )
        if (
            fold.model_unavailable_reason is not None
            or any(value is None for value in core_metrics)
            or fold.bootstrap_valid_count < exact.bootstrap_minimum_valid
        ):
            failed.add(MainForceMirrorDiagnosticGateReason.MODEL_UNAVAILABLE)
        if (
            fold.ridge_score_delta is None
            or fold.ridge_score_ci_lower is None
            or fold.ridge_score_delta < exact.ridge_score_delta_floor
            or (
                exact.ridge_score_ci_lower_strictly_positive
                and fold.ridge_score_ci_lower <= 0
            )
        ):
            failed.add(
                MainForceMirrorDiagnosticGateReason.RIDGE_INCREMENT_INSUFFICIENT
            )
        if (
            fold.full_tree_ridge_delta is None
            or fold.full_tree_ridge_ci_lower is None
            or fold.full_tree_ridge_delta < exact.full_tree_ridge_delta_floor
            or (
                exact.full_tree_ridge_ci_lower_strictly_positive
                and fold.full_tree_ridge_ci_lower <= 0
            )
        ):
            failed.add(
                MainForceMirrorDiagnosticGateReason.NONLINEAR_INCREMENT_INSUFFICIENT
            )
        if (
            fold.full_tree_current_tree_delta is None
            or fold.full_tree_current_tree_ci_lower is None
            or fold.full_tree_current_tree_delta
            < exact.full_tree_current_tree_delta_floor
            or (
                exact.full_tree_current_tree_ci_lower_strictly_positive
                and fold.full_tree_current_tree_ci_lower <= 0
            )
        ):
            failed.add(
                MainForceMirrorDiagnosticGateReason.SEQUENCE_INCREMENT_INSUFFICIENT
            )
        if fold.full_tree_auc is None or fold.full_tree_auc < exact.full_tree_auc_floor:
            failed.add(
                MainForceMirrorDiagnosticGateReason.NONLINEAR_AUC_INSUFFICIENT
            )
        for count, auc, delta, reason in (
            (
                fold.evaluate_long_count,
                fold.long_auc,
                fold.long_point_delta,
                fold.long_unavailable_reason,
            ),
            (
                fold.evaluate_short_count,
                fold.short_auc,
                fold.short_point_delta,
                fold.short_unavailable_reason,
            ),
        ):
            if (
                count < exact.evaluate_each_side_floor
                or reason is not None
                or auc is None
                or delta is None
                or auc < exact.supported_side_auc_floor
                or delta < exact.supported_side_point_delta_floor
            ):
                failed.add(MainForceMirrorDiagnosticGateReason.SIDE_GUARDRAIL_FAILED)
                if reason is not None or auc is None or delta is None:
                    failed.add(MainForceMirrorDiagnosticGateReason.MODEL_UNAVAILABLE)
    if (
        member.t_minus_1_coverage < exact.member_t_minus_1_coverage_floor
        or member.product_count < exact.member_products_floor
        or member.causal_violation_count > exact.member_causal_violations_maximum
        or member.identity_violation_count > exact.member_identity_violations_maximum
    ):
        failed.add(
            MainForceMirrorDiagnosticGateReason.MEMBER_FEASIBILITY_INSUFFICIENT
        )
    reasons = tuple(reason for reason in MainForceMirrorDiagnosticGateReason if reason in failed)
    return MainForceMirrorDiagnosticGateDecision(
        gate=(
            MainForceMirrorDiagnosticGate.STOP
            if reasons
            else MainForceMirrorDiagnosticGate.ALLOW_PHASE_FREEZE_DESIGN
        ),
        reasons=reasons,
    )


def run_main_force_mirror_model_diagnostics(
    datasets: MainForceMirrorDiagnosticFoldDatasets,
) -> MainForceMirrorDiagnosticModelAuditResult:
    """Fit the frozen score/ridge/current-tree/full-tree diagnostics per fold."""

    if (
        not isinstance(datasets, MainForceMirrorDiagnosticFoldDatasets)
        or type(datasets.folds) is not tuple
        or len(datasets.folds) != 2
        or any(
            not isinstance(item, MainForceMirrorDiagnosticFoldDataset)
            for item in datasets.folds
        )
        or any(type(item.fold) is not int for item in datasets.folds)
        or tuple(item.fold for item in datasets.folds) != (1, 2)
    ):
        raise ValueError("MFM_DIAGNOSTIC_ANALYSIS_INVALID")
    fold_sections: list[MainForceMirrorDiagnosticModelFoldSection] = []
    evaluated: list[_EvaluatedFold] = []
    for fold_data, window in zip(datasets.folds, _FOLD_WINDOWS, strict=True):
        section, evaluation = _run_model_fold(fold_data, window)
        fold_sections.append(section)
        evaluated.append(evaluation)
    breakdowns = _model_breakdowns(tuple(evaluated))
    return MainForceMirrorDiagnosticModelAuditResult(
        section=MainForceMirrorDiagnosticModelSection(
            folds=tuple(fold_sections),
            breakdowns=breakdowns,
        )
    )


def _validate_model_sample_structure(sample: object) -> None:
    if type(sample) is not MainForceMirrorDiagnosticModelSample:
        raise ValueError("MFM_DIAGNOSTIC_ANALYSIS_INVALID")
    typed_sample = cast(MainForceMirrorDiagnosticModelSample, sample)
    if (
        type(typed_sample.symbol) is not str
        or not typed_sample.symbol
        or type(typed_sample.physical_contract) is not str
        or not typed_sample.physical_contract
        or type(typed_sample.anchor_trading_day) is not date
        or type(typed_sample.side) is not MainForceMirrorDiagnosticSide
        or type(typed_sample.target) is not int
        or typed_sample.target not in (0, 1)
        or type(typed_sample.features) is not tuple
        or len(typed_sample.features) != 33
        or any(type(value) is not float for value in typed_sample.features)
    ):
        raise ValueError("MFM_DIAGNOSTIC_ANALYSIS_INVALID")
    if any(not isfinite(value) for value in typed_sample.features):
        raise ValueError("MFM_DIAGNOSTIC_ANALYSIS_INVALID")


def _run_model_fold(
    fold_data: MainForceMirrorDiagnosticFoldDataset,
    window: tuple[date, date, date, date],
) -> tuple[MainForceMirrorDiagnosticModelFoldSection, _EvaluatedFold]:
    if (
        not isinstance(fold_data, MainForceMirrorDiagnosticFoldDataset)
        or type(fold_data.fold) is not int
        or fold_data.fold not in (1, 2)
        or type(fold_data.fit) is not tuple
        or type(fold_data.evaluate) is not tuple
    ):
        raise ValueError("MFM_DIAGNOSTIC_ANALYSIS_INVALID")
    fit_samples = fold_data.fit
    evaluate_samples = fold_data.evaluate
    for sample in (*fit_samples, *evaluate_samples):
        _validate_model_sample_structure(sample)
    if any(
        not window[0] <= sample.anchor_trading_day <= window[1]
        for sample in fit_samples
    ) or any(
        not window[2] <= sample.anchor_trading_day <= window[3]
        for sample in evaluate_samples
    ):
        raise ValueError("MFM_DIAGNOSTIC_ANALYSIS_INVALID")
    fit_x = np.asarray([item.features for item in fit_samples], dtype=float)
    fit_y = np.asarray([item.target for item in fit_samples], dtype=float)
    evaluate_x = np.asarray([item.features for item in evaluate_samples], dtype=float)
    evaluate_y = np.asarray([item.target for item in evaluate_samples], dtype=float)
    fit_negative = int(np.sum(fit_y == 0.0))
    fit_positive = int(np.sum(fit_y == 1.0))
    evaluate_negative = int(np.sum(evaluate_y == 0.0))
    evaluate_positive = int(np.sum(evaluate_y == 1.0))
    long_count = sum(
        item.side is MainForceMirrorDiagnosticSide.LONG for item in evaluate_samples
    )
    short_count = len(evaluate_samples) - long_count
    product_count = len({item.symbol for item in evaluate_samples})
    unavailable_reason: MainForceMirrorDiagnosticUnavailableReason | None = None
    predictions: dict[str, np.ndarray] | None = None
    if (
        len(fit_samples) == 0
        or len(evaluate_samples) == 0
        or fit_negative == 0
        or fit_positive == 0
        or evaluate_negative == 0
        or evaluate_positive == 0
    ):
        unavailable_reason = (
            MainForceMirrorDiagnosticUnavailableReason.SPLIT_CLASS_UNAVAILABLE
        )
    else:
        ridge = fit_main_force_mirror_ridge(fit_x, fit_y)
        current_tree = fit_main_force_mirror_cart(
            fit_x, fit_y, feature_count=23
        )
        full_tree = fit_main_force_mirror_cart(
            fit_x, fit_y, feature_count=33
        )
        reasons = tuple(
            item.unavailable_reason
            for item in (ridge, current_tree, full_tree)
            if item.unavailable_reason is not None
        )
        if reasons:
            unavailable_reason = (
                MainForceMirrorDiagnosticUnavailableReason.MODEL_CONVERGENCE_FAILED
                if MainForceMirrorDiagnosticUnavailableReason.MODEL_CONVERGENCE_FAILED
                in reasons
                else MainForceMirrorDiagnosticUnavailableReason.SPLIT_CLASS_UNAVAILABLE
            )
        else:
            assert ridge.model is not None
            assert current_tree.model is not None
            assert full_tree.model is not None
            predictions = {
                "score": evaluate_x[:, 0],
                "ridge": predict_main_force_mirror_ridge(ridge.model, evaluate_x),
                "current_tree": predict_main_force_mirror_cart(
                    current_tree.model, evaluate_x
                ),
                "full_tree": predict_main_force_mirror_cart(
                    full_tree.model, evaluate_x
                ),
            }
    common: dict[str, Any] = dict(
        fold=fold_data.fold,
        fit_since=window[0],
        fit_through=window[1],
        evaluate_since=window[2],
        evaluate_through=window[3],
        fit_binary_count=len(fit_samples),
        fit_negative_count=fit_negative,
        fit_positive_count=fit_positive,
        evaluate_binary_count=len(evaluate_samples),
        evaluate_negative_count=evaluate_negative,
        evaluate_positive_count=evaluate_positive,
        evaluate_long_count=long_count,
        evaluate_short_count=short_count,
        evaluate_product_count=product_count,
    )
    if predictions is None:
        assert unavailable_reason is not None
        section = MainForceMirrorDiagnosticModelFoldSection(
            **common,
            bootstrap_valid_count=0,
            score_auc=None,
            ridge_auc=None,
            current_tree_auc=None,
            full_tree_auc=None,
            ridge_score_delta=None,
            ridge_score_ci_lower=None,
            full_tree_ridge_delta=None,
            full_tree_ridge_ci_lower=None,
            full_tree_current_tree_delta=None,
            full_tree_current_tree_ci_lower=None,
            long_auc=None,
            short_auc=None,
            long_point_delta=None,
            short_point_delta=None,
            model_unavailable_reason=unavailable_reason,
            long_unavailable_reason=unavailable_reason,
            short_unavailable_reason=unavailable_reason,
        )
        return section, _EvaluatedFold(
            fold=fold_data.fold,
            samples=evaluate_samples,
            predictions=None,
            unavailable_reason=unavailable_reason,
        )
    aucs = {
        name: main_force_mirror_auc(evaluate_y, values)
        for name, values in predictions.items()
    }
    if any(value is None for value in aucs.values()):
        raise ValueError("MFM_DIAGNOSTIC_ANALYSIS_INVALID")
    comparisons = (
        ("ridge", "score"),
        ("full_tree", "ridge"),
        ("full_tree", "current_tree"),
    )
    bootstrap = bootstrap_main_force_mirror_auc_deltas(
        evaluate_y,
        np.asarray([item.symbol for item in evaluate_samples], dtype=object),
        predictions,
        comparisons,
    )
    side_values: dict[
        MainForceMirrorDiagnosticSide,
        tuple[Decimal | None, Decimal | None, MainForceMirrorDiagnosticUnavailableReason | None],
    ] = {}
    for side in MainForceMirrorDiagnosticSide:
        mask = np.asarray(
            [item.side is side for item in evaluate_samples], dtype=bool
        )
        full_auc = main_force_mirror_auc(evaluate_y[mask], predictions["full_tree"][mask])
        score_auc = main_force_mirror_auc(evaluate_y[mask], predictions["score"][mask])
        if full_auc is None or score_auc is None:
            side_values[side] = (
                None,
                None,
                MainForceMirrorDiagnosticUnavailableReason.SPLIT_CLASS_UNAVAILABLE,
            )
        else:
            side_values[side] = (
                _decimal_metric(full_auc),
                _decimal_metric(full_auc - score_auc),
                None,
            )
    if bootstrap.valid_count < 1900:
        section = MainForceMirrorDiagnosticModelFoldSection(
            **common,
            bootstrap_valid_count=bootstrap.valid_count,
            score_auc=None,
            ridge_auc=None,
            current_tree_auc=None,
            full_tree_auc=None,
            ridge_score_delta=None,
            ridge_score_ci_lower=None,
            full_tree_ridge_delta=None,
            full_tree_ridge_ci_lower=None,
            full_tree_current_tree_delta=None,
            full_tree_current_tree_ci_lower=None,
            long_auc=side_values[MainForceMirrorDiagnosticSide.LONG][0],
            short_auc=side_values[MainForceMirrorDiagnosticSide.SHORT][0],
            long_point_delta=side_values[MainForceMirrorDiagnosticSide.LONG][1],
            short_point_delta=side_values[MainForceMirrorDiagnosticSide.SHORT][1],
            model_unavailable_reason=(
                MainForceMirrorDiagnosticUnavailableReason.SPLIT_CLASS_UNAVAILABLE
            ),
            long_unavailable_reason=side_values[MainForceMirrorDiagnosticSide.LONG][2],
            short_unavailable_reason=side_values[MainForceMirrorDiagnosticSide.SHORT][2],
        )
        return section, _EvaluatedFold(
            fold=fold_data.fold,
            samples=evaluate_samples,
            predictions=MappingProxyType(
                {
                    name: tuple(float(value) for value in values)
                    for name, values in predictions.items()
                }
            ),
            unavailable_reason=(
                MainForceMirrorDiagnosticUnavailableReason.SPLIT_CLASS_UNAVAILABLE
            ),
        )
    intervals = bootstrap.intervals
    section = MainForceMirrorDiagnosticModelFoldSection(
        **common,
        bootstrap_valid_count=bootstrap.valid_count,
        score_auc=_decimal_metric(aucs["score"]),  # type: ignore[arg-type]
        ridge_auc=_decimal_metric(aucs["ridge"]),  # type: ignore[arg-type]
        current_tree_auc=_decimal_metric(aucs["current_tree"]),  # type: ignore[arg-type]
        full_tree_auc=_decimal_metric(aucs["full_tree"]),  # type: ignore[arg-type]
        ridge_score_delta=_decimal_metric(
            bootstrap.point_deltas[("ridge", "score")]
        ),
        ridge_score_ci_lower=_interval_lower(intervals[("ridge", "score")]),
        full_tree_ridge_delta=_decimal_metric(
            bootstrap.point_deltas[("full_tree", "ridge")]
        ),
        full_tree_ridge_ci_lower=_interval_lower(
            intervals[("full_tree", "ridge")]
        ),
        full_tree_current_tree_delta=_decimal_metric(
            bootstrap.point_deltas[("full_tree", "current_tree")]
        ),
        full_tree_current_tree_ci_lower=_interval_lower(
            intervals[("full_tree", "current_tree")]
        ),
        long_auc=side_values[MainForceMirrorDiagnosticSide.LONG][0],
        short_auc=side_values[MainForceMirrorDiagnosticSide.SHORT][0],
        long_point_delta=side_values[MainForceMirrorDiagnosticSide.LONG][1],
        short_point_delta=side_values[MainForceMirrorDiagnosticSide.SHORT][1],
        long_unavailable_reason=side_values[MainForceMirrorDiagnosticSide.LONG][2],
        short_unavailable_reason=side_values[MainForceMirrorDiagnosticSide.SHORT][2],
    )
    return section, _EvaluatedFold(
        fold=fold_data.fold,
        samples=evaluate_samples,
        predictions=MappingProxyType(
            {name: tuple(float(value) for value in values) for name, values in predictions.items()}
        ),
        unavailable_reason=None,
    )


def _model_breakdowns(
    folds: tuple[_EvaluatedFold, ...],
) -> tuple[MainForceMirrorDiagnosticModelBreakdown, ...]:
    rows: list[MainForceMirrorDiagnosticModelBreakdown] = []
    for key in _expected_breakdown_keys():
        selected: list[tuple[MainForceMirrorDiagnosticModelSample, _EvaluatedFold, int]] = []
        for fold in folds:
            for index, sample in enumerate(fold.samples):
                if _sample_matches_breakdown(sample, fold.fold, key):
                    selected.append((sample, fold, index))
        if not selected:
            rows.append(
                MainForceMirrorDiagnosticModelBreakdown(
                    key=key,
                    sample_count=0,
                    score_auc=None,
                    ridge_auc=None,
                    current_tree_auc=None,
                    full_tree_auc=None,
                )
            )
            continue
        if any(fold.predictions is None for _sample, fold, _index in selected):
            unavailable_reasons = {
                fold.unavailable_reason
                for _sample, fold, _index in selected
                if fold.predictions is None
            }
            if None in unavailable_reasons or not unavailable_reasons:
                raise ValueError("MFM_DIAGNOSTIC_ANALYSIS_INVALID")
            unavailable_reason = (
                MainForceMirrorDiagnosticUnavailableReason.MODEL_CONVERGENCE_FAILED
                if MainForceMirrorDiagnosticUnavailableReason.MODEL_CONVERGENCE_FAILED
                in unavailable_reasons
                else MainForceMirrorDiagnosticUnavailableReason.SPLIT_CLASS_UNAVAILABLE
            )
            rows.append(
                MainForceMirrorDiagnosticModelBreakdown(
                    key=key,
                    sample_count=len(selected),
                    score_auc=None,
                    ridge_auc=None,
                    current_tree_auc=None,
                    full_tree_auc=None,
                    unavailable_reason=unavailable_reason,
                )
            )
            continue
        targets = np.asarray([sample.target for sample, _fold, _index in selected])
        cohort_aucs: dict[str, float | None] = {}
        for name in ("score", "ridge", "current_tree", "full_tree"):
            prediction = np.asarray(
                [
                    cast(Mapping[str, tuple[float, ...]], fold.predictions)[name][
                        index
                    ]
                    for _sample, fold, index in selected
                ],
                dtype=float,
            )
            cohort_aucs[name] = main_force_mirror_auc(targets, prediction)
        if any(value is None for value in cohort_aucs.values()):
            rows.append(
                MainForceMirrorDiagnosticModelBreakdown(
                    key=key,
                    sample_count=len(selected),
                    score_auc=None,
                    ridge_auc=None,
                    current_tree_auc=None,
                    full_tree_auc=None,
                    unavailable_reason=(
                        MainForceMirrorDiagnosticUnavailableReason.SPLIT_CLASS_UNAVAILABLE
                    ),
                )
            )
        else:
            rows.append(
                MainForceMirrorDiagnosticModelBreakdown(
                    key=key,
                    sample_count=len(selected),
                    score_auc=_decimal_metric(cohort_aucs["score"]),  # type: ignore[arg-type]
                    ridge_auc=_decimal_metric(cohort_aucs["ridge"]),  # type: ignore[arg-type]
                    current_tree_auc=_decimal_metric(cohort_aucs["current_tree"]),  # type: ignore[arg-type]
                    full_tree_auc=_decimal_metric(cohort_aucs["full_tree"]),  # type: ignore[arg-type]
                )
            )
    return tuple(rows)


def _sample_matches_breakdown(
    sample: MainForceMirrorDiagnosticModelSample,
    fold: int,
    key: MainForceMirrorDiagnosticBreakdownKey,
) -> bool:
    if key.scope is MainForceMirrorDiagnosticBreakdownScope.GLOBAL:
        return True
    if key.scope is MainForceMirrorDiagnosticBreakdownScope.PRODUCT:
        return key.product == sample.symbol
    if key.scope is MainForceMirrorDiagnosticBreakdownScope.YEAR:
        return key.year == sample.anchor_trading_day.year
    if key.scope is MainForceMirrorDiagnosticBreakdownScope.SIDE:
        return key.side is sample.side
    return key.fold == fold


def _decimal_metric(value: float) -> Decimal:
    if not isfinite(value):
        raise ValueError("MFM_DIAGNOSTIC_ANALYSIS_INVALID")
    return Decimal(str(float(value)))


def _interval_lower(value: tuple[float, float] | None) -> Decimal | None:
    return None if value is None else _decimal_metric(value[0])


def _sequence_profile_stable(
    protocol: MainForceMirrorDiagnosticProtocol,
    profile: object,
) -> bool:
    return bool(
        getattr(profile, "peak_then_decay_sample_count", -1)
        >= protocol.sequence_peak_then_decay_pooled_floor
        and getattr(profile, "long_sample_count", -1)
        >= protocol.sequence_each_side_floor
        and getattr(profile, "short_sample_count", -1)
        >= protocol.sequence_each_side_floor
        and getattr(profile, "product_count", -1) >= protocol.sequence_products_floor
        and getattr(profile, "year_count", -1) >= protocol.sequence_years_floor
        and getattr(profile, "top_product_share", Decimal(2))
        <= protocol.sequence_top_product_share_maximum
        and getattr(profile, "median_delay_bars", None) is not None
        and getattr(profile, "median_delay_bars")
        <= protocol.sequence_median_delay_maximum_bars
        and getattr(profile, "h3_reversal_hit_rate", None) is not None
        and getattr(profile, "h3_reversal_hit_rate")
        >= protocol.sequence_h3_h5_reversal_hit_floor
        and getattr(profile, "h5_reversal_hit_rate", None) is not None
        and getattr(profile, "h5_reversal_hit_rate")
        >= protocol.sequence_h3_h5_reversal_hit_floor
        and getattr(profile, "yearly_median_reversal_min", None) is not None
        and getattr(profile, "yearly_median_reversal_min")
        >= protocol.sequence_yearly_side_median_floor
        and getattr(profile, "side_median_reversal_min", None) is not None
        and getattr(profile, "side_median_reversal_min")
        >= protocol.sequence_yearly_side_median_floor
    )


def _build_cart_node(
    features: np.ndarray,
    targets: np.ndarray,
    weights: np.ndarray,
    indices: np.ndarray,
    thresholds: tuple[tuple[float, ...], ...],
    *,
    depth: int,
) -> MainForceMirrorDiagnosticCartNode:
    probability = _leaf_probability(targets[indices], weights[indices])
    if depth >= 2:
        return MainForceMirrorDiagnosticCartNode(probability=probability)
    parent_gini = _weighted_gini(targets[indices], weights[indices])
    parent_weight = float(np.sum(weights[indices]))
    best: tuple[int, float, np.ndarray, np.ndarray] | None = None
    best_decrease = 0.0
    for feature_index, feature_thresholds in enumerate(thresholds):
        for threshold in feature_thresholds:
            left_mask = features[indices, feature_index] <= threshold
            left = indices[left_mask]
            right = indices[~left_mask]
            if len(left) < 50 or len(right) < 50:
                continue
            left_weight = float(np.sum(weights[left]))
            right_weight = float(np.sum(weights[right]))
            decrease = parent_gini - (
                left_weight * _weighted_gini(targets[left], weights[left])
                + right_weight * _weighted_gini(targets[right], weights[right])
            ) / parent_weight
            if decrease > best_decrease:
                best_decrease = decrease
                best = (feature_index, threshold, left, right)
    if best is None:
        return MainForceMirrorDiagnosticCartNode(probability=probability)
    feature_index, threshold, left, right = best
    return MainForceMirrorDiagnosticCartNode(
        probability=probability,
        feature_index=feature_index,
        threshold=threshold,
        left=_build_cart_node(
            features, targets, weights, left, thresholds, depth=depth + 1
        ),
        right=_build_cart_node(
            features, targets, weights, right, thresholds, depth=depth + 1
        ),
    )


def _weighted_gini(targets: np.ndarray, weights: np.ndarray) -> float:
    total = float(np.sum(weights))
    if total <= 0:
        raise ValueError("MFM_DIAGNOSTIC_ANALYSIS_INVALID")
    positive = float(np.sum(weights[targets == 1.0])) / total
    return 1.0 - positive * positive - (1.0 - positive) * (1.0 - positive)


def _leaf_probability(targets: np.ndarray, weights: np.ndarray) -> float:
    positive = float(np.sum(weights[targets == 1.0]))
    total = float(np.sum(weights))
    return (positive + 1.0) / (total + 2.0)


def _cart_probability(
    node: MainForceMirrorDiagnosticCartNode,
    row: np.ndarray,
) -> float:
    current = node
    while current.feature_index is not None:
        assert current.threshold is not None
        assert current.left is not None and current.right is not None
        current = (
            current.left
            if row[current.feature_index] <= current.threshold
            else current.right
        )
    return current.probability


def _sigmoid(logits: np.ndarray) -> np.ndarray:
    clipped = np.clip(logits, -35.0, 35.0)
    return 1.0 / (1.0 + np.exp(-clipped))


def _feature_matrix(value: np.ndarray) -> np.ndarray:
    result = np.asarray(value, dtype=float)
    if result.ndim != 2 or result.shape[1] == 0:
        raise ValueError("MFM_DIAGNOSTIC_ANALYSIS_INVALID")
    return result


def _target_vector(value: np.ndarray) -> np.ndarray:
    result = np.asarray(value, dtype=float)
    if (
        result.ndim != 1
        or not np.all(np.isfinite(result))
        or not np.all(np.isin(result, (0.0, 1.0)))
    ):
        raise ValueError("MFM_DIAGNOSTIC_ANALYSIS_INVALID")
    return result


def _number(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        result = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return None
    return result if isfinite(result) else None


def _numbers(values: tuple[object, ...]) -> tuple[float, ...] | None:
    result = tuple(_number(value) for value in values)
    if any(value is None for value in result):
        return None
    return cast(tuple[float, ...], result)
