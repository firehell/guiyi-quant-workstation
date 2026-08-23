"""Pure in-memory audits for Main Force Mirror diagnostic Phase A."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum
from math import isfinite
from typing import Never

from guiyi_quant.indicators.main_force_mirror_v2 import (
    MainForceMirrorV2AuditTraceItem,
    MainForceMirrorV2Point,
)

from app.market_data.domain import CanonicalBar
from app.research.main_force.main_force_mirror_diagnostic import (
    MainForceMirrorDiagnosticBreakdownKey,
    MainForceMirrorDiagnosticBreakdownScope,
    MainForceMirrorDiagnosticFunnelSection,
    MainForceMirrorDiagnosticLabelBreakdown,
    MainForceMirrorDiagnosticLabelSection,
    MainForceMirrorDiagnosticScoreLatchBreakdown,
    MainForceMirrorDiagnosticPrefixInvariance,
    MainForceMirrorDiagnosticSequenceBreakdown,
    MainForceMirrorDiagnosticSequenceEvent,
    MainForceMirrorDiagnosticSequenceEventCount,
    MainForceMirrorDiagnosticSequenceProfileSection,
    MainForceMirrorDiagnosticSequenceSection,
    MainForceMirrorDiagnosticSequenceState,
    MainForceMirrorDiagnosticSequenceTransitionCount,
    MainForceMirrorDiagnosticSide,
    MainForceMirrorDiagnosticUnavailableReason,
    _expected_breakdown_keys,
)
from app.research.main_force.main_force_mirror_v2_research_service import (
    MainForceMirrorV2SequenceFact,
    SEQUENCE_PROFILES,
    _derive_sequence_facts,
)


_HORIZON = 10
_FOLD_WINDOWS = (
    (date(2023, 1, 1), date(2024, 12, 31), date(2025, 1, 1), date(2025, 12, 31)),
    (date(2023, 1, 1), date(2025, 12, 31), date(2026, 1, 1), date(2026, 8, 18)),
)
class MainForceMirrorDiagnosticAnalysisError(ValueError):
    code = "MFM_DIAGNOSTIC_ANALYSIS_INVALID"

    def __init__(self) -> None:
        super().__init__(self.code)


class MainForceMirrorDiagnosticLabelOutcome(StrEnum):
    ADVERSE_FIRST = "adverse_first"
    FAVORABLE_FIRST = "favorable_first"
    AMBIGUOUS = "ambiguous"
    TIMEOUT = "timeout"
    CENSORED_HORIZON = "censored_horizon"
    CENSORED_CONTRACT_CHANGE = "censored_contract_change"
    CENSORED_INPUT_GAP = "censored_input_gap"
    SPLIT_BOUNDARY_CENSORED = "split_boundary_censored"


class MainForceMirrorDiagnosticLegacyOutcome(StrEnum):
    LONG_ONLY = "long_only"
    SHORT_ONLY = "short_only"
    BOTH = "both"
    NEITHER = "neither"


@dataclass(frozen=True, slots=True)
class MainForceMirrorDiagnosticFoldLabelOutcome:
    fold: int
    segment: str
    outcome: MainForceMirrorDiagnosticLabelOutcome | None
    binary_target: int | None
    eligible: bool


@dataclass(frozen=True, slots=True)
class MainForceMirrorDiagnosticProductInput:
    symbol: str
    bars: tuple[CanonicalBar, ...]
    points: tuple[MainForceMirrorV2Point, ...]
    trace: tuple[MainForceMirrorV2AuditTraceItem, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "bars", tuple(self.bars))
        object.__setattr__(self, "points", tuple(self.points))
        object.__setattr__(self, "trace", tuple(self.trace))


@dataclass(frozen=True, slots=True)
class MainForceMirrorDiagnosticLabelEpisode:
    symbol: str
    anchor_index: int
    anchor_trading_day: date
    physical_contract: str
    side: MainForceMirrorDiagnosticSide
    kept: bool
    lower_barrier: Decimal
    upper_barrier: Decimal
    legacy_outcome: MainForceMirrorDiagnosticLegacyOutcome
    outcome: MainForceMirrorDiagnosticLabelOutcome | None
    first_touch_offset: int | None
    binary_target: int | None
    fold_outcomes: tuple[MainForceMirrorDiagnosticFoldLabelOutcome, ...]


@dataclass(frozen=True, slots=True)
class MainForceMirrorDiagnosticLabelAuditResult:
    inputs: tuple[MainForceMirrorDiagnosticProductInput, ...]
    section: MainForceMirrorDiagnosticLabelSection
    episodes: tuple[MainForceMirrorDiagnosticLabelEpisode, ...]
    unavailable_products: tuple[
        tuple[str, MainForceMirrorDiagnosticUnavailableReason], ...
    ]


@dataclass(frozen=True, slots=True)
class MainForceMirrorDiagnosticSequenceFactSet:
    symbol: str
    profile_id: str
    facts: tuple[MainForceMirrorV2SequenceFact, ...]


@dataclass(frozen=True, slots=True)
class MainForceMirrorDiagnosticSequenceAuditResult:
    section: MainForceMirrorDiagnosticSequenceSection
    fact_sets: tuple[MainForceMirrorDiagnosticSequenceFactSet, ...]


@dataclass(frozen=True, slots=True)
class _SequenceSample:
    symbol: str
    trading_day: date
    side: MainForceMirrorDiagnosticSide
    delay: int
    h3_reversal: Decimal
    h5_reversal: Decimal


def audit_main_force_mirror_sequences(
    products: tuple[MainForceMirrorDiagnosticProductInput, ...],
    *,
    trading_day_scope: tuple[date, date] | None = None,
) -> MainForceMirrorDiagnosticSequenceAuditResult:
    """Audit all frozen strict-prior sequence profiles without selecting one."""

    inputs = tuple(products)
    scope = _normalize_trading_day_scope(trading_day_scope)
    if len({item.symbol for item in inputs}) != len(inputs):
        _raise_analysis_invalid()
    fact_sets: list[MainForceMirrorDiagnosticSequenceFactSet] = []
    sections: list[MainForceMirrorDiagnosticSequenceProfileSection] = []
    for profile in SEQUENCE_PROFILES:
        profile_facts: list[
            tuple[MainForceMirrorDiagnosticProductInput, tuple[MainForceMirrorV2SequenceFact, ...]]
        ] = []
        for item in inputs:
            _validate_product_input(item)
            facts = _derive_sequence_facts(item.points, profile)
            if len(facts) != len(item.points):
                _raise_analysis_invalid()
            profile_facts.append((item, facts))
            fact_sets.append(
                MainForceMirrorDiagnosticSequenceFactSet(
                    symbol=item.symbol,
                    profile_id=profile.profile_id,
                    facts=tuple(
                        fact
                        for bar, fact in zip(item.bars, facts, strict=True)
                        if _trading_day_in_scope(bar.trading_day, scope)
                    ),
                )
            )
        sections.append(
            _sequence_profile_section(
                profile.profile_id,
                profile_facts,
                profile,
                scope,
            )
        )
    fact_sets.sort(
        key=lambda item: (
            tuple(profile.profile_id for profile in SEQUENCE_PROFILES).index(
                item.profile_id
            ),
            item.symbol,
        )
    )
    return MainForceMirrorDiagnosticSequenceAuditResult(
        section=MainForceMirrorDiagnosticSequenceSection(profiles=tuple(sections)),
        fact_sets=tuple(fact_sets),
    )


def _sequence_profile_section(
    profile_id: str,
    product_facts: list[
        tuple[MainForceMirrorDiagnosticProductInput, tuple[MainForceMirrorV2SequenceFact, ...]]
    ],
    profile: object,
    trading_day_scope: tuple[date, date] | None,
) -> MainForceMirrorDiagnosticSequenceProfileSection:
    keys = _expected_breakdown_keys()
    counts = {key: _new_sequence_counts() for key in keys}
    transitions: dict[
        MainForceMirrorDiagnosticBreakdownKey,
        dict[tuple[MainForceMirrorDiagnosticSequenceState, MainForceMirrorDiagnosticSequenceState], int],
    ] = {key: defaultdict(int) for key in keys}
    events: dict[
        MainForceMirrorDiagnosticBreakdownKey,
        dict[MainForceMirrorDiagnosticSequenceEvent, list[int]],
    ] = {key: defaultdict(lambda: [0, 0, 0]) for key in keys}
    prefixes = {key: [0, 0, 0] for key in keys}
    samples: list[_SequenceSample] = []
    for item, facts in product_facts:
        states = tuple(_sequence_state(fact) for fact in facts)
        block_ids = _physical_block_ids(item)
        previous_state: MainForceMirrorDiagnosticSequenceState | None = None
        previous_side = MainForceMirrorDiagnosticSide.LONG
        for index, (fact, state) in enumerate(zip(facts, states, strict=True)):
            counted = _trading_day_in_scope(
                item.bars[index].trading_day,
                trading_day_scope,
            )
            if index == 0 or block_ids[index] != block_ids[index - 1]:
                previous_state = None
                previous_side = MainForceMirrorDiagnosticSide.LONG
            side = _sequence_fact_side(fact, previous_side)
            previous_side = side
            dimension_keys = _bar_keys(item.symbol, item.bars[index].trading_day, side)
            installed_keys: (
                tuple[MainForceMirrorDiagnosticBreakdownKey, ...] | None
            ) = None
            if (
                fact.installed_peak_index is not None
                and fact.installed_peak_side is not None
            ):
                installed_side = (
                    MainForceMirrorDiagnosticSide.LONG
                    if fact.installed_peak_side == "long"
                    else MainForceMirrorDiagnosticSide.SHORT
                )
                installed_keys = _bar_keys(
                    item.symbol,
                    item.bars[index].trading_day,
                    installed_side,
                )
            active_keys = dimension_keys
            if fact.active_peak_side is not None:
                active_side = (
                    MainForceMirrorDiagnosticSide.LONG
                    if fact.active_peak_side == "long"
                    else MainForceMirrorDiagnosticSide.SHORT
                )
                active_keys = _bar_keys(
                    item.symbol,
                    item.bars[index].trading_day,
                    active_side,
                )
            if counted and previous_state is not None and state is not previous_state:
                for key in dimension_keys:
                    transitions[key][(previous_state, state)] += 1
            previous_state = state
            active_events = _sequence_events(fact)
            dual = fact.peak_seen and len(active_events) > 1
            if counted:
                for event_kind in active_events:
                    event_keys = (
                        installed_keys
                        if event_kind is MainForceMirrorDiagnosticSequenceEvent.PEAK
                        and installed_keys is not None
                        else active_keys
                    )
                    for key in event_keys:
                        event_counts = events[key][event_kind]
                        event_counts[0] += 1
                        event_counts[1] += 1
                        event_counts[2] += int(dual)
                if (
                    fact.installed_peak_index is not None
                    and fact.installed_peak_side is not None
                ):
                    assert installed_keys is not None
                    for key in installed_keys:
                        counts[key]["raw_episode_count"] += 1
                        counts[key]["kept_episode_count"] += 1
                    prefix = _derive_sequence_facts(
                        item.points[: index + 1],  # type: ignore[arg-type]
                        profile,  # type: ignore[arg-type]
                    )
                    matches = bool(prefix and prefix[-1] == fact)
                    for key in installed_keys:
                        prefixes[key][0] += 1
                        prefixes[key][1] += int(matches)
                        prefixes[key][2] += int(not matches)
            if (
                not counted
                or not fact.decay_seen
                or fact.active_peak_side is None
            ):
                continue
            if fact.active_peak_index is None or fact.bars_since_active_peak is None:
                _raise_analysis_invalid()
            peak_index = fact.active_peak_index
            peak_side = (
                MainForceMirrorDiagnosticSide.LONG
                if fact.active_peak_side == "long"
                else MainForceMirrorDiagnosticSide.SHORT
            )
            attribution_day = (
                item.bars[index].trading_day
                if trading_day_scope is not None
                else item.bars[peak_index].trading_day
            )
            peak_keys = _bar_keys(
                item.symbol,
                attribution_day,
                peak_side,
            )
            for key in peak_keys:
                counts[key]["first_evidence_count"] += 1
                counts[key]["delay_sample_count"] += 1
                counts[key]["delay_bars_total"] += fact.bars_since_active_peak
            h3 = _sequence_reversal(item, index, fact.active_peak_side, 3)
            h5 = _sequence_reversal(item, index, fact.active_peak_side, 5)
            if h3 is None or h5 is None:
                continue
            sample = _SequenceSample(
                symbol=item.symbol,
                trading_day=attribution_day,
                side=peak_side,
                delay=fact.bars_since_active_peak,
                h3_reversal=h3,
                h5_reversal=h5,
            )
            samples.append(sample)
    breakdowns = tuple(
        MainForceMirrorDiagnosticSequenceBreakdown(
            key=key,
            **counts[key],
            transitions=tuple(
                MainForceMirrorDiagnosticSequenceTransitionCount(
                    from_state=source,
                    to_state=target,
                    count=count,
                )
                for (source, target), count in sorted(
                    transitions[key].items(),
                    key=lambda item: (item[0][0].value, item[0][1].value),
                )
                if count
            ),
            events=tuple(
                MainForceMirrorDiagnosticSequenceEventCount(
                    event_kind=event_kind,
                    raw_count=events[key][event_kind][0],
                    kept_count=events[key][event_kind][1],
                    overlap_count=events[key][event_kind][2],
                )
                for event_kind in MainForceMirrorDiagnosticSequenceEvent
                if events[key][event_kind][0]
            ),
            prefix_invariance=MainForceMirrorDiagnosticPrefixInvariance(
                checked_prefix_count=prefixes[key][0],
                matching_prefix_count=prefixes[key][1],
                mismatch_count=prefixes[key][2],
            ),
        )
        for key in keys
    )
    product_counts: dict[str, int] = defaultdict(int)
    year_values: dict[int, list[Decimal]] = defaultdict(list)
    side_values: dict[MainForceMirrorDiagnosticSide, list[Decimal]] = defaultdict(list)
    for sample in samples:
        product_counts[sample.symbol] += 1
        year_values[sample.trading_day.year].append(sample.h5_reversal)
        side_values[sample.side].append(sample.h5_reversal)
    sample_count = len(samples)
    if sample_count == 0:
        return MainForceMirrorDiagnosticSequenceProfileSection(
            profile_id=profile_id,
            peak_then_decay_sample_count=0,
            long_sample_count=0,
            short_sample_count=0,
            product_count=0,
            year_count=0,
            top_product_share=Decimal(0),
            median_delay_bars=None,
            h3_reversal_hit_rate=None,
            h5_reversal_hit_rate=None,
            yearly_median_reversal_min=None,
            side_median_reversal_min=None,
            breakdowns=breakdowns,
        )
    return MainForceMirrorDiagnosticSequenceProfileSection(
        profile_id=profile_id,
        peak_then_decay_sample_count=sample_count,
        long_sample_count=sum(
            sample.side is MainForceMirrorDiagnosticSide.LONG for sample in samples
        ),
        short_sample_count=sum(
            sample.side is MainForceMirrorDiagnosticSide.SHORT for sample in samples
        ),
        product_count=len(product_counts),
        year_count=len(year_values),
        top_product_share=Decimal(max(product_counts.values())) / Decimal(sample_count),
        median_delay_bars=_median_decimal(
            tuple(Decimal(sample.delay) for sample in samples)
        ),
        h3_reversal_hit_rate=Decimal(
            sum(sample.h3_reversal > 0 for sample in samples)
        )
        / Decimal(sample_count),
        h5_reversal_hit_rate=Decimal(
            sum(sample.h5_reversal > 0 for sample in samples)
        )
        / Decimal(sample_count),
        yearly_median_reversal_min=min(
            _median_decimal(tuple(values)) for values in year_values.values()
        ),
        side_median_reversal_min=min(
            _median_decimal(tuple(values)) for values in side_values.values()
        ),
        breakdowns=breakdowns,
    )


def _new_sequence_counts() -> dict[str, int]:
    return {
        "raw_episode_count": 0,
        "kept_episode_count": 0,
        "overlap_suppressed_count": 0,
        "first_evidence_count": 0,
        "delay_sample_count": 0,
        "delay_bars_total": 0,
    }


def _sequence_state(
    fact: MainForceMirrorV2SequenceFact,
) -> MainForceMirrorDiagnosticSequenceState:
    if fact.peak_seen:
        return MainForceMirrorDiagnosticSequenceState.PEAK
    if fact.accumulated_reversal_seen:
        return MainForceMirrorDiagnosticSequenceState.ACCUMULATED_REVERSAL
    if fact.opposite_build_seen:
        return MainForceMirrorDiagnosticSequenceState.OPPOSITE_BUILD
    if fact.liquidation_seen:
        return MainForceMirrorDiagnosticSequenceState.LIQUIDATION
    if fact.decay_seen:
        return MainForceMirrorDiagnosticSequenceState.DECAY
    if fact.pressure_state in ("long_build", "short_build"):
        return MainForceMirrorDiagnosticSequenceState.BUILD
    return MainForceMirrorDiagnosticSequenceState.IDLE


def _sequence_events(
    fact: MainForceMirrorV2SequenceFact,
) -> tuple[MainForceMirrorDiagnosticSequenceEvent, ...]:
    return tuple(
        event
        for present, event in (
            (fact.peak_seen, MainForceMirrorDiagnosticSequenceEvent.PEAK),
            (fact.decay_seen, MainForceMirrorDiagnosticSequenceEvent.DECAY),
            (fact.liquidation_seen, MainForceMirrorDiagnosticSequenceEvent.LIQUIDATION),
            (fact.opposite_build_seen, MainForceMirrorDiagnosticSequenceEvent.OPPOSITE_BUILD),
            (
                fact.accumulated_reversal_seen,
                MainForceMirrorDiagnosticSequenceEvent.ACCUMULATED_REVERSAL,
            ),
        )
        if present
    )


def _sequence_fact_side(
    fact: MainForceMirrorV2SequenceFact,
    fallback: MainForceMirrorDiagnosticSide,
) -> MainForceMirrorDiagnosticSide:
    side = fact.active_peak_side or fact.installed_peak_side
    if side is None and fact.current_side in ("long", "short"):
        side = fact.current_side
    if side == "short":
        return MainForceMirrorDiagnosticSide.SHORT
    if side == "long":
        return MainForceMirrorDiagnosticSide.LONG
    return fallback


def _sequence_reversal(
    item: MainForceMirrorDiagnosticProductInput,
    index: int,
    side: str,
    horizon: int,
) -> Decimal | None:
    target = index + horizon
    if target >= len(item.bars):
        return None
    contract = item.points[index].physical_contract
    if contract is None:
        return None
    for future_index in range(index, target + 1):
        if (
            item.points[future_index].physical_contract != contract
            or item.points[future_index].unavailable_reason is not None
            or item.trace[future_index].unavailable_reason is not None
            or not _valid_bar(item.bars[future_index])
        ):
            return None
    source = _decimal(item.bars[index].close)
    future = _decimal(item.bars[target].close)
    if source is None or future is None or source <= 0:
        return None
    return (
        (source - future) / source
        if side == "long"
        else (future - source) / source
    )


def _median_decimal(values: tuple[Decimal, ...]) -> Decimal:
    ordered = sorted(values)
    midpoint = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[midpoint]
    return (ordered[midpoint - 1] + ordered[midpoint]) / Decimal(2)


def _normalize_trading_day_scope(
    value: tuple[date, date] | None,
) -> tuple[date, date] | None:
    if value is None:
        return None
    if (
        type(value) is not tuple
        or len(value) != 2
        or type(value[0]) is not date
        or type(value[1]) is not date
        or value[0] > value[1]
    ):
        _raise_analysis_invalid()
    return value


def _trading_day_in_scope(
    trading_day: date,
    scope: tuple[date, date] | None,
) -> bool:
    return scope is None or scope[0] <= trading_day <= scope[1]


def audit_main_force_mirror_funnel(
    products: tuple[MainForceMirrorDiagnosticProductInput, ...],
    labels: MainForceMirrorDiagnosticLabelAuditResult,
    *,
    trading_day_scope: tuple[date, date] | None = None,
) -> MainForceMirrorDiagnosticFunnelSection:
    """Explain the frozen unrounded score-to-latch path and sampling funnel."""

    inputs = tuple(products)
    scope = _normalize_trading_day_scope(trading_day_scope)
    if not isinstance(labels, MainForceMirrorDiagnosticLabelAuditResult):
        _raise_analysis_invalid()
    if labels.inputs != inputs:
        _raise_analysis_invalid()
    if labels != audit_main_force_mirror_labels(
        inputs,
        trading_day_scope=scope,
    ):
        _raise_analysis_invalid()
    counters = {key: _new_funnel_counts() for key in _expected_breakdown_keys()}
    for item in inputs:
        _validate_product_input(item)
        if any(symbol == item.symbol for symbol, _reason in labels.unavailable_products):
            continue
        actual_anchors: set[int] = set()
        for index, (bar, point, trace) in enumerate(
            zip(item.bars, item.points, item.trace, strict=True)
        ):
            counted = _trading_day_in_scope(bar.trading_day, scope)
            if not point.caution_ready:
                if (
                    trace.long_candidate not in (None, False)
                    or trace.short_candidate not in (None, False)
                    or trace.trigger is not None
                ):
                    _raise_analysis_invalid()
                continue
            long_score = _decimal(trace.long_score)
            short_score = _decimal(trace.short_score)
            if long_score is None or short_score is None:
                _raise_analysis_invalid()
            long_high = long_score >= Decimal(70)
            short_high = short_score >= Decimal(70)
            if (
                trace.long_candidate is not long_high
                or trace.short_candidate is not short_high
                or trace.conflict is not (long_high and short_high)
            ):
                _raise_analysis_invalid()
            side = _funnel_side(trace, long_high, short_high)
            keys = _bar_keys(item.symbol, bar.trading_day, side) if counted else ()
            for key in keys:
                counters[key]["caution_ready_bar_count"] += 1
            if not long_high and not short_high:
                if (
                    trace.trigger is not None
                    or trace.long_disarmed_suppressed
                    or trace.short_disarmed_suppressed
                ):
                    _raise_analysis_invalid()
                for key in keys:
                    counters[key]["score_not_candidate_count"] += 1
            elif long_high and short_high:
                if (
                    trace.trigger is not None
                    or trace.long_disarmed_suppressed
                    or trace.short_disarmed_suppressed
                ):
                    _raise_analysis_invalid()
                for key in keys:
                    counters[key]["dual_candidate_conflict_count"] += 1
                    counters[key]["high_score_unique_bar_count"] += 1
            else:
                candidate_side = (
                    MainForceMirrorDiagnosticSide.LONG
                    if long_high
                    else MainForceMirrorDiagnosticSide.SHORT
                )
                expected_trigger = (
                    "long_chase_caution"
                    if candidate_side is MainForceMirrorDiagnosticSide.LONG
                    else "short_chase_caution"
                )
                suppressed = (
                    trace.long_disarmed_suppressed
                    if candidate_side is MainForceMirrorDiagnosticSide.LONG
                    else trace.short_disarmed_suppressed
                )
                opposite_suppressed = (
                    trace.short_disarmed_suppressed
                    if candidate_side is MainForceMirrorDiagnosticSide.LONG
                    else trace.long_disarmed_suppressed
                )
                if opposite_suppressed or (trace.trigger == expected_trigger) == suppressed:
                    _raise_analysis_invalid()
                for key in keys:
                    counters[key][
                        f"{candidate_side.value}_only_candidate_count"
                    ] += 1
                    counters[key]["high_score_unique_bar_count"] += 1
                    if trace.trigger == expected_trigger:
                        counters[key]["armed_candidate_count"] += 1
                    else:
                        counters[key]["unarmed_candidate_suppressed_count"] += 1
                if counted and trace.trigger == expected_trigger:
                    actual_anchors.add(index)
                    for key in keys:
                        counters[key][f"{candidate_side.value}_caution_count"] += 1
                        counters[key]["caution_count"] += 1
            if any(reason.startswith("long_") for reason in trace.rearm_reasons):
                for key in keys:
                    counters[key]["long_rearm_count"] += 1
            if any(reason.startswith("short_") for reason in trace.rearm_reasons):
                for key in keys:
                    counters[key]["short_rearm_count"] += 1
        expected_anchors = {
            episode.anchor_index
            for episode in labels.episodes
            if episode.symbol == item.symbol
        }
        if actual_anchors != expected_anchors:
            _raise_analysis_invalid()
    for episode in labels.episodes:
        for key in _episode_keys(episode):
            counters[key]["raw_episode_anchor_count"] += 1
            if episode.kept:
                counters[key]["kept_episode_anchor_count"] += 1
            else:
                counters[key]["overlap_suppressed_anchor_count"] += 1
        if not episode.kept:
            continue
        if episode.binary_target is not None:
            for key in _nonfold_episode_keys(episode):
                counters[key]["binary_evaluable_count"] += 1
        for fold_outcome in episode.fold_outcomes:
            if fold_outcome.binary_target is not None:
                counters[_fold_key(fold_outcome.fold)][
                    "binary_evaluable_count"
                ] += 1
    breakdowns = tuple(
        MainForceMirrorDiagnosticScoreLatchBreakdown(key=key, **counters[key])
        for key in _expected_breakdown_keys()
    )
    global_counts = counters[breakdowns[0].key]
    return MainForceMirrorDiagnosticFunnelSection(
        evaluable_bar_count=global_counts["caution_ready_bar_count"],
        binary_evaluable_count=global_counts["binary_evaluable_count"],
        high_score_bar_count=global_counts["high_score_unique_bar_count"],
        conflict_bar_count=global_counts["dual_candidate_conflict_count"],
        armed_bar_count=global_counts["armed_candidate_count"],
        caution_episode_count=global_counts["caution_count"],
        latched_episode_count=global_counts["caution_count"],
        suppression_count=global_counts["unarmed_candidate_suppressed_count"],
        raw_episode_anchor_count=global_counts["raw_episode_anchor_count"],
        kept_episode_anchor_count=global_counts["kept_episode_anchor_count"],
        overlap_suppressed_anchor_count=global_counts[
            "overlap_suppressed_anchor_count"
        ],
        breakdowns=breakdowns,
    )


def audit_main_force_mirror_labels(
    products: tuple[MainForceMirrorDiagnosticProductInput, ...],
    *,
    trading_day_scope: tuple[date, date] | None = None,
) -> MainForceMirrorDiagnosticLabelAuditResult:
    """Build frozen 10-Bar first-touch labels without reading external state."""

    inputs = tuple(products)
    scope = _normalize_trading_day_scope(trading_day_scope)
    if len({item.symbol for item in inputs}) != len(inputs):
        _raise_analysis_invalid()
    episodes: list[MainForceMirrorDiagnosticLabelEpisode] = []
    unavailable: list[tuple[str, MainForceMirrorDiagnosticUnavailableReason]] = []
    for item in inputs:
        _validate_product_input(item)
        audited = _label_product(item, scope)
        if audited is None:
            unavailable.append(
                (
                    item.symbol,
                    MainForceMirrorDiagnosticUnavailableReason.LABEL_BARRIER_INVALID,
                )
            )
        else:
            episodes.extend(audited)
    section = _label_section(tuple(episodes))
    return MainForceMirrorDiagnosticLabelAuditResult(
        inputs=inputs,
        section=section,
        episodes=tuple(episodes),
        unavailable_products=tuple(unavailable),
    )


def _validate_product_input(value: MainForceMirrorDiagnosticProductInput) -> None:
    if (
        not isinstance(value, MainForceMirrorDiagnosticProductInput)
        or value.symbol not in {key.product for key in _expected_breakdown_keys() if key.product}
        or len(value.bars) != len(value.points)
        or len(value.bars) != len(value.trace)
    ):
        _raise_analysis_invalid()
    previous_end = None
    for bar, point, trace in zip(value.bars, value.points, value.trace, strict=True):
        if (
            not isinstance(bar, CanonicalBar)
            or not isinstance(point, MainForceMirrorV2Point)
            or not isinstance(trace, MainForceMirrorV2AuditTraceItem)
            or bar.bar_end != point.bar_end
            or bar.bar_end != trace.bar_end
            or bar.trading_day != point.trading_day
            or bar.trading_day != trace.trading_day
            or point.physical_contract != trace.physical_contract
            or point.caution != trace.trigger
            or point.caution_conflict != trace.conflict
            or (previous_end is not None and bar.bar_end <= previous_end)
        ):
            _raise_analysis_invalid()
        previous_end = bar.bar_end


def _label_product(
    value: MainForceMirrorDiagnosticProductInput,
    trading_day_scope: tuple[date, date] | None,
) -> tuple[MainForceMirrorDiagnosticLabelEpisode, ...] | None:
    block_ids = _physical_block_ids(value)
    raw_indices = tuple(
        index
        for index, point in enumerate(value.points)
        if point.caution in ("long_chase_caution", "short_chase_caution")
        and not point.caution_conflict
        and (
            trading_day_scope is None
            or value.bars[index].trading_day <= trading_day_scope[1]
        )
    )
    last_kept_by_block: dict[int, int] = {}
    result: list[MainForceMirrorDiagnosticLabelEpisode] = []
    for index in raw_indices:
        point = value.points[index]
        trace = value.trace[index]
        contract = point.physical_contract
        if contract is None:
            _raise_analysis_invalid()
        close = _decimal(value.bars[index].close)
        atr = _decimal(trace.atr14)
        if close is None or atr is None or close <= 0 or atr <= 0:
            return None
        lower = close - atr
        upper = close + atr
        if lower <= 0 or upper <= lower:
            return None
        side = (
            MainForceMirrorDiagnosticSide.LONG
            if point.caution == "long_chase_caution"
            else MainForceMirrorDiagnosticSide.SHORT
        )
        block_id = block_ids[index]
        previous_kept = last_kept_by_block.get(block_id)
        kept = previous_kept is None or index - previous_kept > _HORIZON
        if kept:
            last_kept_by_block[block_id] = index
        legacy = _legacy_outcome(value, index, contract, lower, upper)
        outcome: MainForceMirrorDiagnosticLabelOutcome | None = None
        first_touch: int | None = None
        binary: int | None = None
        if kept:
            outcome, first_touch = _first_touch_outcome(
                value, index, contract, side, lower, upper
            )
            if outcome is MainForceMirrorDiagnosticLabelOutcome.ADVERSE_FIRST:
                binary = 1
            elif outcome is MainForceMirrorDiagnosticLabelOutcome.FAVORABLE_FIRST:
                binary = 0
        if _trading_day_in_scope(point.trading_day, trading_day_scope):
            result.append(
                MainForceMirrorDiagnosticLabelEpisode(
                    symbol=value.symbol,
                    anchor_index=index,
                    anchor_trading_day=point.trading_day,
                    physical_contract=contract,
                    side=side,
                    kept=kept,
                    lower_barrier=lower,
                    upper_barrier=upper,
                    legacy_outcome=legacy,
                    outcome=outcome,
                    first_touch_offset=first_touch,
                    binary_target=binary,
                    fold_outcomes=_fold_label_outcomes(
                        value,
                        index,
                        kept,
                        outcome,
                        binary,
                    ),
                )
            )
    return tuple(result)


def _physical_block_ids(
    value: MainForceMirrorDiagnosticProductInput,
) -> tuple[int, ...]:
    result: list[int] = []
    block_id = -1
    previous_contract: str | None = None
    previous_unavailable = True
    for point, trace in zip(value.points, value.trace, strict=True):
        unavailable = (
            point.physical_contract is None
            or point.unavailable_reason is not None
            or trace.unavailable_reason is not None
            or trace.reset_boundary is not None
        )
        if (
            not result
            or point.physical_contract != previous_contract
            or unavailable
            or previous_unavailable
        ):
            block_id += 1
        result.append(block_id)
        previous_contract = point.physical_contract
        previous_unavailable = unavailable
    return tuple(result)


def _first_touch_outcome(
    value: MainForceMirrorDiagnosticProductInput,
    anchor_index: int,
    contract: str,
    side: MainForceMirrorDiagnosticSide,
    lower: Decimal,
    upper: Decimal,
) -> tuple[MainForceMirrorDiagnosticLabelOutcome, int | None]:
    for offset in range(1, _HORIZON + 1):
        index = anchor_index + offset
        if index >= len(value.bars):
            return MainForceMirrorDiagnosticLabelOutcome.CENSORED_HORIZON, None
        point = value.points[index]
        trace = value.trace[index]
        if point.physical_contract != contract:
            return (
                MainForceMirrorDiagnosticLabelOutcome.CENSORED_CONTRACT_CHANGE,
                None,
            )
        if (
            point.unavailable_reason is not None
            or trace.unavailable_reason is not None
            or not _valid_bar(value.bars[index])
        ):
            return MainForceMirrorDiagnosticLabelOutcome.CENSORED_INPUT_GAP, None
        bar = value.bars[index]
        open_ = _decimal(bar.open)
        high = _decimal(bar.high)
        low = _decimal(bar.low)
        assert open_ is not None and high is not None and low is not None
        if open_ >= upper:
            touched = "upper"
        elif open_ <= lower:
            touched = "lower"
        elif high >= upper and low <= lower:
            return MainForceMirrorDiagnosticLabelOutcome.AMBIGUOUS, offset
        elif high >= upper:
            touched = "upper"
        elif low <= lower:
            touched = "lower"
        else:
            continue
        adverse = (
            touched == "lower"
            if side is MainForceMirrorDiagnosticSide.LONG
            else touched == "upper"
        )
        return (
            MainForceMirrorDiagnosticLabelOutcome.ADVERSE_FIRST
            if adverse
            else MainForceMirrorDiagnosticLabelOutcome.FAVORABLE_FIRST,
            offset,
        )
    return MainForceMirrorDiagnosticLabelOutcome.TIMEOUT, None


def _fold_label_outcomes(
    value: MainForceMirrorDiagnosticProductInput,
    anchor_index: int,
    kept: bool,
    physical_outcome: MainForceMirrorDiagnosticLabelOutcome | None,
    physical_binary: int | None,
) -> tuple[MainForceMirrorDiagnosticFoldLabelOutcome, ...]:
    anchor_day = value.bars[anchor_index].trading_day
    horizon_index = anchor_index + _HORIZON
    result: list[MainForceMirrorDiagnosticFoldLabelOutcome] = []
    for fold, segment, since, through in _fold_segments_for_day(anchor_day):
        outcome: MainForceMirrorDiagnosticLabelOutcome | None
        binary: int | None
        crosses_segment = (
            horizon_index < len(value.bars)
            and not since <= value.bars[horizon_index].trading_day <= through
        )
        if kept and crosses_segment:
            outcome = MainForceMirrorDiagnosticLabelOutcome.SPLIT_BOUNDARY_CENSORED
            binary = None
        else:
            outcome = physical_outcome if kept else None
            binary = physical_binary if kept else None
        result.append(
            MainForceMirrorDiagnosticFoldLabelOutcome(
                fold=fold,
                segment=segment,
                outcome=outcome,
                binary_target=binary,
                eligible=binary is not None,
            )
        )
    return tuple(result)


def _legacy_outcome(
    value: MainForceMirrorDiagnosticProductInput,
    anchor_index: int,
    contract: str,
    lower: Decimal,
    upper: Decimal,
) -> MainForceMirrorDiagnosticLegacyOutcome:
    lower_seen = False
    upper_seen = False
    end = min(len(value.bars), anchor_index + _HORIZON + 1)
    for index in range(anchor_index + 1, end):
        point = value.points[index]
        trace = value.trace[index]
        bar = value.bars[index]
        if (
            point.physical_contract != contract
            or point.unavailable_reason is not None
            or trace.unavailable_reason is not None
            or not _valid_bar(bar)
        ):
            break
        high = _decimal(bar.high)
        low = _decimal(bar.low)
        assert high is not None and low is not None
        lower_seen = lower_seen or low <= lower
        upper_seen = upper_seen or high >= upper
    if lower_seen and upper_seen:
        return MainForceMirrorDiagnosticLegacyOutcome.BOTH
    if lower_seen:
        return MainForceMirrorDiagnosticLegacyOutcome.LONG_ONLY
    if upper_seen:
        return MainForceMirrorDiagnosticLegacyOutcome.SHORT_ONLY
    return MainForceMirrorDiagnosticLegacyOutcome.NEITHER


def _label_section(
    episodes: tuple[MainForceMirrorDiagnosticLabelEpisode, ...],
) -> MainForceMirrorDiagnosticLabelSection:
    counters = {key: _new_label_counts() for key in _expected_breakdown_keys()}
    for episode in episodes:
        raw_keys = _episode_keys(episode)
        for key in raw_keys:
            counts = counters[key]
            counts["raw_sample_count"] += 1
            counts[f"legacy_{episode.legacy_outcome.value}_count"] += 1
            if not episode.kept:
                counts["overlap_suppressed_count"] += 1
        if not episode.kept:
            continue
        for key in raw_keys:
            counts = counters[key]
            counts["kept_sample_count"] += 1
            counts["long_sample_count"] += 1
            counts["short_sample_count"] += 1
            counts["duplicated_side_sample_count"] += 1
        for key in _nonfold_episode_keys(episode):
            counts = counters[key]
            if episode.binary_target is not None:
                counts["binary_evaluable_count"] += 1
            assert episode.outcome is not None
            counts[_OUTCOME_COUNT_FIELD[episode.outcome]] += 1
        for fold_outcome in episode.fold_outcomes:
            key = _fold_key(fold_outcome.fold)
            if fold_outcome.binary_target is not None:
                counters[key]["binary_evaluable_count"] += 1
            assert fold_outcome.outcome is not None
            counters[key][_OUTCOME_COUNT_FIELD[fold_outcome.outcome]] += 1
    breakdowns = tuple(
        MainForceMirrorDiagnosticLabelBreakdown(key=key, **counters[key])
        for key in _expected_breakdown_keys()
    )
    global_counts = counters[breakdowns[0].key]
    sample_count = global_counts["kept_sample_count"]
    resolved = (
        Decimal(0)
        if sample_count == 0
        else Decimal(global_counts["binary_evaluable_count"]) / Decimal(sample_count)
    )
    ambiguous = (
        Decimal(0)
        if sample_count == 0
        else Decimal(global_counts["ambiguous_count"]) / Decimal(sample_count)
    )
    return MainForceMirrorDiagnosticLabelSection(
        raw_sample_count=global_counts["raw_sample_count"],
        sample_count=sample_count,
        overlap_suppressed_count=global_counts["overlap_suppressed_count"],
        long_sample_count=global_counts["long_sample_count"],
        short_sample_count=global_counts["short_sample_count"],
        duplicated_side_sample_count=global_counts["duplicated_side_sample_count"],
        binary_evaluable_count=global_counts["binary_evaluable_count"],
        legacy_long_only_count=global_counts["legacy_long_only_count"],
        legacy_short_only_count=global_counts["legacy_short_only_count"],
        legacy_both_count=global_counts["legacy_both_count"],
        legacy_neither_count=global_counts["legacy_neither_count"],
        adverse_first_count=global_counts["adverse_first_count"],
        favorable_first_count=global_counts["favorable_first_count"],
        ambiguous_count=global_counts["ambiguous_count"],
        timeout_count=global_counts["timeout_count"],
        censored_horizon_count=global_counts["censored_horizon_count"],
        censored_contract_change_count=global_counts[
            "censored_contract_change_count"
        ],
        censored_input_gap_count=global_counts["censored_input_gap_count"],
        split_boundary_censored_count=global_counts[
            "split_boundary_censored_count"
        ],
        resolved_coverage=resolved,
        ambiguous_rate=ambiguous,
        breakdowns=breakdowns,
    )


def _episode_keys(
    episode: MainForceMirrorDiagnosticLabelEpisode,
) -> tuple[MainForceMirrorDiagnosticBreakdownKey, ...]:
    wanted = (
        (MainForceMirrorDiagnosticBreakdownScope.GLOBAL, None),
        (MainForceMirrorDiagnosticBreakdownScope.PRODUCT, episode.symbol),
        (MainForceMirrorDiagnosticBreakdownScope.YEAR, episode.anchor_trading_day.year),
        (MainForceMirrorDiagnosticBreakdownScope.SIDE, episode.side),
        *((MainForceMirrorDiagnosticBreakdownScope.FOLD, item.fold) for item in episode.fold_outcomes),
    )
    return tuple(
        key
        for key in _expected_breakdown_keys()
        if any(_key_matches(key, scope, value) for scope, value in wanted)
    )


def _nonfold_episode_keys(
    episode: MainForceMirrorDiagnosticLabelEpisode,
) -> tuple[MainForceMirrorDiagnosticBreakdownKey, ...]:
    return tuple(
        key
        for key in _episode_keys(episode)
        if key.scope is not MainForceMirrorDiagnosticBreakdownScope.FOLD
    )


def _fold_key(fold: int) -> MainForceMirrorDiagnosticBreakdownKey:
    return next(
        key
        for key in _expected_breakdown_keys()
        if key.scope is MainForceMirrorDiagnosticBreakdownScope.FOLD
        and key.fold == fold
    )


def _key_matches(
    key: MainForceMirrorDiagnosticBreakdownKey,
    scope: MainForceMirrorDiagnosticBreakdownScope,
    value: object,
) -> bool:
    if key.scope is not scope:
        return False
    if scope is MainForceMirrorDiagnosticBreakdownScope.GLOBAL:
        return True
    if scope is MainForceMirrorDiagnosticBreakdownScope.PRODUCT:
        return key.product == value
    if scope is MainForceMirrorDiagnosticBreakdownScope.YEAR:
        return key.year == value
    if scope is MainForceMirrorDiagnosticBreakdownScope.SIDE:
        return key.side == value
    return key.fold == value


def _new_label_counts() -> dict[str, int]:
    return {
        field: 0
        for field in MainForceMirrorDiagnosticLabelBreakdown.__dataclass_fields__
        if field != "key"
    }


def _new_funnel_counts() -> dict[str, int]:
    return {
        field: 0
        for field in MainForceMirrorDiagnosticScoreLatchBreakdown.__dataclass_fields__
        if field != "key"
    }


def _bar_keys(
    symbol: str,
    trading_day: date,
    side: MainForceMirrorDiagnosticSide,
) -> tuple[MainForceMirrorDiagnosticBreakdownKey, ...]:
    placeholder = MainForceMirrorDiagnosticLabelEpisode(
        symbol=symbol,
        anchor_index=0,
        anchor_trading_day=trading_day,
        physical_contract="placeholder",
        side=side,
        kept=False,
        lower_barrier=Decimal(1),
        upper_barrier=Decimal(2),
        legacy_outcome=MainForceMirrorDiagnosticLegacyOutcome.NEITHER,
        outcome=None,
        first_touch_offset=None,
        binary_target=None,
        fold_outcomes=tuple(
            MainForceMirrorDiagnosticFoldLabelOutcome(
                fold=fold,
                segment=segment,
                outcome=None,
                binary_target=None,
                eligible=False,
            )
            for fold, segment, _since, _through in _fold_segments_for_day(trading_day)
        ),
    )
    return _episode_keys(placeholder)


def _funnel_side(
    trace: MainForceMirrorV2AuditTraceItem,
    long_high: bool,
    short_high: bool,
) -> MainForceMirrorDiagnosticSide:
    if long_high != short_high:
        return (
            MainForceMirrorDiagnosticSide.LONG
            if long_high
            else MainForceMirrorDiagnosticSide.SHORT
        )
    direction = _decimal(trace.direction)
    if direction is not None and direction < 0:
        return MainForceMirrorDiagnosticSide.SHORT
    return MainForceMirrorDiagnosticSide.LONG


_OUTCOME_COUNT_FIELD = {
    MainForceMirrorDiagnosticLabelOutcome.ADVERSE_FIRST: "adverse_first_count",
    MainForceMirrorDiagnosticLabelOutcome.FAVORABLE_FIRST: "favorable_first_count",
    MainForceMirrorDiagnosticLabelOutcome.AMBIGUOUS: "ambiguous_count",
    MainForceMirrorDiagnosticLabelOutcome.TIMEOUT: "timeout_count",
    MainForceMirrorDiagnosticLabelOutcome.CENSORED_HORIZON: "censored_horizon_count",
    MainForceMirrorDiagnosticLabelOutcome.CENSORED_CONTRACT_CHANGE: (
        "censored_contract_change_count"
    ),
    MainForceMirrorDiagnosticLabelOutcome.CENSORED_INPUT_GAP: (
        "censored_input_gap_count"
    ),
    MainForceMirrorDiagnosticLabelOutcome.SPLIT_BOUNDARY_CENSORED: (
        "split_boundary_censored_count"
    ),
}


def _fold_segments_for_day(
    value: date,
) -> tuple[tuple[int, str, date, date], ...]:
    result: list[tuple[int, str, date, date]] = []
    for fold, (fit_since, fit_through, evaluate_since, evaluate_through) in enumerate(
        _FOLD_WINDOWS, 1
    ):
        if fit_since <= value <= fit_through:
            result.append((fold, "fit", fit_since, fit_through))
        elif evaluate_since <= value <= evaluate_through:
            result.append((fold, "evaluate", evaluate_since, evaluate_through))
    return tuple(result)


def _valid_bar(value: CanonicalBar) -> bool:
    open_ = _decimal(value.open)
    high = _decimal(value.high)
    low = _decimal(value.low)
    close = _decimal(value.close)
    volume = _decimal(value.volume)
    return (
        open_ is not None
        and high is not None
        and low is not None
        and close is not None
        and volume is not None
        and open_ > 0
        and close > 0
        and volume >= 0
        and low > 0
        and low <= open_ <= high
        and low <= close <= high
    )


def _decimal(value: object) -> Decimal | None:
    if isinstance(value, Decimal):
        return value if value.is_finite() else None
    if isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value):
        return Decimal(str(value))
    return None


def _raise_analysis_invalid() -> Never:
    raise MainForceMirrorDiagnosticAnalysisError()
