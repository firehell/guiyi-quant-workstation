"""Typed product replay over the existing Newow formula primitives."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from decimal import Decimal

from .escape_d123 import EscapeState, initial_escape_state, step_escape_d123
from .main_rise import (
    MAIN_RISE_PAGE_V1,
    MainRiseState,
    MainRiseStepResult,
    initial_main_rise_state,
    step_main_rise,
)
from .models import NewowMainMarker, TrendBandState
from .oscillation_channel import (
    CHANNEL_FORMULA_VERSION,
    OSCILLATION_FORMULA_VERSION,
    OscillationState,
    OscillationStepResult,
    step_oscillation,
)
from .product_contracts import (
    ActionKind,
    EvidenceStatus,
    FeatureRuntimeStatus,
    FeatureStatus,
    MainState,
    ProductBar,
    ProductIdentity,
    ProductStrategy,
    StrategyAction,
    StrategyFrame,
    StrategyHint,
    StrategyReplay,
    TradeEligibility,
)
from .profile import NEWOW_TREND_D1_PAGE_V2
from .trend_band import (
    TrendBandStateValue,
    initial_trend_band_state,
    step_trend_band,
)


_TREND_FORMULAS = frozenset(
    (
        NEWOW_TREND_D1_PAGE_V2.trend_band_formula,
        NEWOW_TREND_D1_PAGE_V2.escape_formula,
    )
)
_OSCILLATION_FORMULAS = frozenset(
    (OSCILLATION_FORMULA_VERSION, CHANNEL_FORMULA_VERSION)
)
_MAIN_RISE_FORMULAS = frozenset(
    (
        MAIN_RISE_PAGE_V1.band_formula,
        MAIN_RISE_PAGE_V1.j_reduce_formula,
        MAIN_RISE_PAGE_V1.escape_formula,
        MAIN_RISE_PAGE_V1.buy_formula,
        MAIN_RISE_PAGE_V1.magic11_formula,
    )
)
_EXPECTED_FORMULAS = {
    ProductStrategy.TREND: _TREND_FORMULAS,
    ProductStrategy.OSCILLATION: _OSCILLATION_FORMULAS,
    ProductStrategy.MAIN_RISE: _MAIN_RISE_FORMULAS,
}
_ACTIVE = EvidenceStatus.ACTIVE_CODE_VERIFIED


@dataclass(slots=True)
class _PairingState:
    eligible_build: StrategyAction | None = None
    prewarm_build: StrategyAction | None = None
    source_builds: dict[str, StrategyAction] = field(default_factory=dict)


def _metric(value: float | None) -> Decimal | None:
    return None if value is None else Decimal(str(value))


def _ready() -> FeatureStatus:
    return FeatureStatus(FeatureRuntimeStatus.READY, _ACTIVE)


def _warming(code: str) -> FeatureStatus:
    return FeatureStatus(FeatureRuntimeStatus.WARMING, _ACTIVE, code)


def _unavailable(code: str) -> FeatureStatus:
    return FeatureStatus(FeatureRuntimeStatus.UNAVAILABLE, _ACTIVE, code)


def _validate_inputs(identity: ProductIdentity, bars: tuple[ProductBar, ...]) -> None:
    if not isinstance(identity, ProductIdentity):
        raise ValueError("NEWOW_PRODUCT_INVALID_IDENTITY")
    if frozenset(identity.formula_versions) != _EXPECTED_FORMULAS[identity.strategy]:
        raise ValueError("NEWOW_PRODUCT_FORMULA_IDENTITY_INVALID")
    seen_segments: set[str] = set()
    current_segment: str | None = None
    current_contract: str | None = None
    previous_bar = None
    for product_bar in bars:
        if (
            not isinstance(product_bar, ProductBar)
            or product_bar.bar.product != identity.product
            or product_bar.frequency != identity.frequency
            or product_bar.series_kind != identity.series_kind
        ):
            raise ValueError("NEWOW_PRODUCT_INPUT_IDENTITY_INVALID")
        bar = product_bar.bar
        if bar.segment_id != current_segment:
            if bar.segment_id in seen_segments:
                raise ValueError("NEWOW_PRODUCT_INPUT_ORDER")
            if current_segment is not None:
                seen_segments.add(current_segment)
            current_segment = bar.segment_id
            current_contract = bar.physical_contract
            previous_bar = None
        elif bar.physical_contract != current_contract:
            raise ValueError("NEWOW_PRODUCT_INPUT_IDENTITY_INVALID")
        if previous_bar is not None and (
            bar.bar_end <= previous_bar.bar_end
            or bar.trading_day < previous_bar.trading_day
        ):
            raise ValueError("NEWOW_PRODUCT_INPUT_ORDER")
        previous_bar = bar


def _new_action(
    identity: ProductIdentity,
    product_bar: ProductBar,
    kind: ActionKind | str,
    price: Decimal,
    sequence: int,
    *,
    source_marker_id: str | None = None,
    source_related_marker_ids: tuple[str, ...] = (),
    trade_eligibility: TradeEligibility = TradeEligibility.ELIGIBLE,
) -> StrategyAction:
    return StrategyAction(
        identity=identity,
        physical_contract=product_bar.bar.physical_contract,
        segment_id=product_bar.bar.segment_id,
        bar_end=product_bar.bar.bar_end,
        trading_day=product_bar.bar.trading_day,
        kind=ActionKind(kind),
        reference_price=price,
        anchor_price=price,
        sequence=sequence,
        source_marker_id=source_marker_id,
        source_related_marker_ids=source_related_marker_ids,
        trade_eligibility=trade_eligibility,
    )


def _record_warmup_build(
    pairing: _PairingState, action: StrategyAction
) -> StrategyAction:
    if action.kind is not ActionKind.BUILD:
        raise ValueError("NEWOW_PRODUCT_PAIRING_CONFLICT")
    pairing.prewarm_build = action
    if action.source_marker_id is not None:
        existing = pairing.source_builds.get(action.source_marker_id)
        if existing is not None and existing != action:
            raise ValueError("NEWOW_PRODUCT_PAIRING_CONFLICT")
        pairing.source_builds[action.source_marker_id] = action
    return action


def _pair_action(
    pairing: _PairingState,
    action: StrategyAction,
    *,
    referenced: StrategyAction | None = None,
) -> StrategyAction:
    if action.kind is ActionKind.BUILD:
        if pairing.eligible_build is not None:
            raise ValueError("NEWOW_PRODUCT_PAIRING_CONFLICT")
        pairing.prewarm_build = None
        pairing.eligible_build = action
        if action.source_marker_id is not None:
            existing = pairing.source_builds.get(action.source_marker_id)
            if existing is not None and existing != action:
                raise ValueError("NEWOW_PRODUCT_PAIRING_CONFLICT")
            pairing.source_builds[action.source_marker_id] = action
        return action

    entry = referenced or pairing.eligible_build or pairing.prewarm_build
    if entry is None or entry.kind is not ActionKind.BUILD:
        raise ValueError("NEWOW_PRODUCT_PAIRING_CONFLICT")
    if (
        entry.identity != action.identity
        or entry.physical_contract != action.physical_contract
        or entry.segment_id != action.segment_id
    ):
        raise ValueError("NEWOW_PRODUCT_PAIRING_CONFLICT")
    if referenced is not None and referenced not in (
        pairing.eligible_build,
        pairing.prewarm_build,
    ):
        raise ValueError("NEWOW_PRODUCT_PAIRING_CONFLICT")
    eligibility = (
        TradeEligibility.ELIGIBLE
        if entry.trade_eligibility is TradeEligibility.ELIGIBLE
        else TradeEligibility.NO_ELIGIBLE_ENTRY
    )
    paired = replace(
        action,
        related_build_id=entry.signal_id,
        trade_eligibility=eligibility,
    )
    if entry is pairing.eligible_build:
        pairing.eligible_build = None
    else:
        pairing.prewarm_build = None
    return paired


def _trend_action(
    identity: ProductIdentity,
    product_bar: ProductBar,
    marker: NewowMainMarker,
    pairing: _PairingState,
    *,
    eligibility: TradeEligibility = TradeEligibility.ELIGIBLE,
) -> StrategyAction:
    if marker.marker_type not in (ActionKind.BUILD, ActionKind.CLEAR):
        raise ValueError("NEWOW_PRODUCT_PAIRING_CONFLICT")
    action = _new_action(
        identity,
        product_bar,
        marker.marker_type,
        marker.price,
        0,
        source_marker_id=marker.marker_id,
        source_related_marker_ids=marker.related_marker_ids,
        trade_eligibility=eligibility,
    )
    if action.kind is ActionKind.BUILD:
        if marker.related_marker_ids:
            raise ValueError("NEWOW_PRODUCT_PAIRING_CONFLICT")
        return (
            _record_warmup_build(pairing, action)
            if eligibility is TradeEligibility.WARMUP_ONLY
            else _pair_action(pairing, action)
        )
    if len(marker.related_marker_ids) != 1:
        raise ValueError("NEWOW_PRODUCT_PAIRING_CONFLICT")
    referenced = pairing.source_builds.get(marker.related_marker_ids[0])
    if referenced is None:
        raise ValueError("NEWOW_PRODUCT_PAIRING_CONFLICT")
    return _pair_action(pairing, action, referenced=referenced)


def _hint(
    identity: ProductIdentity,
    product_bar: ProductBar,
    kind: str,
    price: Decimal,
    *,
    source_marker_id: str | None = None,
    source_related_marker_ids: tuple[str, ...] = (),
) -> StrategyHint:
    return StrategyHint(
        identity=identity,
        physical_contract=product_bar.bar.physical_contract,
        segment_id=product_bar.bar.segment_id,
        bar_end=product_bar.bar.bar_end,
        trading_day=product_bar.bar.trading_day,
        kind=kind,
        known_at=product_bar.bar.bar_end,
        anchor_price=price,
        source_marker_id=source_marker_id,
        source_related_marker_ids=source_related_marker_ids,
    )


def _escape_hints(
    identity: ProductIdentity,
    product_bar: ProductBar,
    markers: tuple[NewowMainMarker, ...],
) -> tuple[StrategyHint, ...]:
    return tuple(
        _hint(
            identity,
            product_bar,
            marker.marker_type.value,
            marker.price,
            source_marker_id=marker.marker_id,
            source_related_marker_ids=marker.related_marker_ids,
        )
        for marker in markers
    )


def _trend_frame(
    identity: ProductIdentity,
    product_bar: ProductBar,
    state: TrendBandStateValue,
    escape_state: EscapeState,
    pairing: _PairingState,
) -> tuple[StrategyFrame, TrendBandStateValue, EscapeState, tuple[str, ...]]:
    raw_bar = product_bar.bar
    result = step_trend_band(state, raw_bar, profile=NEWOW_TREND_D1_PAGE_V2)
    escape = step_escape_d123(escape_state, raw_bar, profile=NEWOW_TREND_D1_PAGE_V2)
    diagnostics: list[str] = []
    actions: tuple[StrategyAction, ...] = ()
    next_state = result.state
    if raw_bar.observation_eligible and result.marker is not None:
        action = _trend_action(identity, product_bar, result.marker, pairing)
        actions = (action,)
        if action.trade_eligibility is TradeEligibility.NO_ELIGIBLE_ENTRY:
            diagnostics.append("NO_ELIGIBLE_ENTRY")
    elif not raw_bar.observation_eligible:
        witness = step_trend_band(
            state,
            replace(raw_bar, observation_eligible=True),
            profile=NEWOW_TREND_D1_PAGE_V2,
        )
        # The primitive suppresses both the marker and its source-link state on
        # pre-owner bars. Preserve that formula state without promoting a main
        # action; the retained WARMUP_ONLY witness is the only pairing proof.
        next_state = witness.state
        if witness.marker is not None:
            if witness.marker.marker_type == ActionKind.BUILD:
                actions = (
                    _trend_action(
                        identity,
                        product_bar,
                        witness.marker,
                        pairing,
                        eligibility=TradeEligibility.WARMUP_ONLY,
                    ),
                )
            else:
                related = witness.marker.related_marker_ids
                if (
                    len(related) != 1
                    or pairing.source_builds.get(related[0])
                    is not pairing.prewarm_build
                ):
                    raise ValueError("NEWOW_PRODUCT_PAIRING_CONFLICT")
                pairing.prewarm_build = None
    point = result.point
    main_state = (
        MainState.BUILD
        if actions
        and actions[-1].kind is ActionKind.BUILD
        and actions[-1].trade_eligibility is TradeEligibility.ELIGIBLE
        else MainState.CLEAR
        if actions and actions[-1].kind is ActionKind.CLEAR
        else MainState.HOLD
        if point.state is TrendBandState.YELLOW
        else MainState.FLAT
        if point.state is TrendBandState.BLUE
        else MainState.UNAVAILABLE
    )
    availability = (
        _unavailable("NEWOW_TREND_UNAVAILABLE")
        if point.state is TrendBandState.UNAVAILABLE
        else _ready()
    )
    frame = StrategyFrame(
        product_bar,
        main_state,
        (("a", _metric(point.b_value)), ("b", _metric(point.c_value))),
        availability,
        actions,
        _escape_hints(identity, product_bar, escape.markers),
    )
    return frame, next_state, escape.state, tuple(diagnostics)


def _oscillation_actions(
    identity: ProductIdentity,
    product_bar: ProductBar,
    result: OscillationStepResult,
    pairing: _PairingState,
) -> tuple[StrategyAction, ...]:
    actions = []
    for sequence, signal in enumerate(result.signals):
        action = _new_action(
            identity,
            product_bar,
            signal.action,
            signal.price,
            sequence,
        )
        actions.append(_pair_action(pairing, action))
    return tuple(actions)


def _oscillation_witnesses(
    identity: ProductIdentity,
    product_bar: ProductBar,
    state: OscillationState,
    pairing: _PairingState,
) -> tuple[StrategyAction, ...]:
    shadow = step_oscillation(
        state, replace(product_bar.bar, observation_eligible=True)
    )
    witnesses = []
    for sequence, signal in enumerate(shadow.signals):
        if signal.action == ActionKind.CLEAR:
            pairing.prewarm_build = None
            continue
        action = _new_action(
            identity,
            product_bar,
            signal.action,
            signal.price,
            sequence,
            trade_eligibility=TradeEligibility.WARMUP_ONLY,
        )
        witnesses.append(_record_warmup_build(pairing, action))
    return tuple(witnesses)


def _oscillation_frame(
    identity: ProductIdentity,
    product_bar: ProductBar,
    state: OscillationState,
    pairing: _PairingState,
) -> tuple[StrategyFrame, OscillationState, tuple[str, ...]]:
    result = step_oscillation(state, product_bar.bar)
    actions = (
        _oscillation_actions(identity, product_bar, result, pairing)
        if product_bar.bar.observation_eligible
        else _oscillation_witnesses(identity, product_bar, state, pairing)
    )
    diagnostics = list(result.diagnostics)
    diagnostics.extend(
        "NO_ELIGIBLE_ENTRY"
        for action in actions
        if action.trade_eligibility is TradeEligibility.NO_ELIGIBLE_ENTRY
    )
    channel = result.channel
    values = (
        (
            ("upper", None),
            ("lower", None),
            ("width", None),
            ("close_position", None),
        )
        if channel is None
        else (
            ("upper", channel.upper),
            ("lower", channel.lower),
            ("width", channel.width),
            ("close_position", channel.close_position),
        )
    )
    main_state = (
        MainState.BUILD
        if actions
        and actions[-1].kind is ActionKind.BUILD
        and actions[-1].trade_eligibility is TradeEligibility.ELIGIBLE
        else MainState.CLEAR
        if actions and actions[-1].kind is ActionKind.CLEAR
        else MainState.HOLD
        if result.state.holding
        else MainState.FLAT
    )
    availability = (
        _unavailable(result.diagnostics[0])
        if result.diagnostics
        else _warming("NEWOW_OSCILLATION_WARMING")
        if result.state.history_count < 10
        else _ready()
    )
    return (
        StrategyFrame(product_bar, main_state, values, availability, actions),
        result.state,
        tuple(diagnostics),
    )


def _main_rise_actions(
    identity: ProductIdentity,
    product_bar: ProductBar,
    result: MainRiseStepResult,
    pairing: _PairingState,
) -> tuple[StrategyAction, ...]:
    if result.band_signal is None:
        return ()
    signal = result.band_signal
    action = _new_action(identity, product_bar, signal.action, signal.price, 0)
    return (_pair_action(pairing, action),)


def _main_rise_witnesses(
    identity: ProductIdentity,
    product_bar: ProductBar,
    state: MainRiseState,
    pairing: _PairingState,
) -> tuple[StrategyAction, ...]:
    shadow = step_main_rise(
        state,
        replace(product_bar.bar, observation_eligible=True),
        formulas=MAIN_RISE_PAGE_V1,
    )
    signal = shadow.band_signal
    if signal is None:
        return ()
    if signal.action == ActionKind.CLEAR:
        pairing.prewarm_build = None
        return ()
    action = _new_action(
        identity,
        product_bar,
        signal.action,
        signal.price,
        0,
        trade_eligibility=TradeEligibility.WARMUP_ONLY,
    )
    return (_record_warmup_build(pairing, action),)


def _main_rise_hints(
    identity: ProductIdentity,
    product_bar: ProductBar,
    result: MainRiseStepResult,
) -> tuple[StrategyHint, ...]:
    hints = list(_escape_hints(identity, product_bar, result.escape_markers))
    if result.reduce_signal is not None:
        hints.append(_hint(identity, product_bar, "J", result.reduce_signal.price))
    hints.extend(
        _hint(identity, product_bar, marker.kind.value, marker.price)
        for marker in result.buy_markers
    )
    if result.magic11.marker is not None:
        marker = result.magic11.marker
        hints.append(
            _hint(
                identity,
                product_bar,
                f"MAGIC11:{marker.label.value}",
                marker.price,
            )
        )
    return tuple(hints)


def _main_rise_frame(
    identity: ProductIdentity,
    product_bar: ProductBar,
    state: MainRiseState,
    pairing: _PairingState,
) -> tuple[StrategyFrame, MainRiseState, tuple[str, ...]]:
    result = step_main_rise(state, product_bar.bar, formulas=MAIN_RISE_PAGE_V1)
    actions = (
        _main_rise_actions(identity, product_bar, result, pairing)
        if product_bar.bar.observation_eligible
        else _main_rise_witnesses(identity, product_bar, state, pairing)
    )
    diagnostics = list(result.diagnostics)
    diagnostics.extend(
        "NO_ELIGIBLE_ENTRY"
        for action in actions
        if action.trade_eligibility is TradeEligibility.NO_ELIGIBLE_ENTRY
    )
    main_state = (
        MainState.BUILD
        if actions
        and actions[-1].kind is ActionKind.BUILD
        and actions[-1].trade_eligibility is TradeEligibility.ELIGIBLE
        else MainState.CLEAR
        if actions and actions[-1].kind is ActionKind.CLEAR
        else MainState.HOLD
        if result.band_state is TrendBandState.YELLOW
        else MainState.FLAT
        if result.band_state is TrendBandState.BLUE
        else MainState.UNAVAILABLE
    )
    availability = (
        _unavailable(result.diagnostics[0]) if result.diagnostics else _ready()
    )
    frame = StrategyFrame(
        product_bar,
        main_state,
        (("ma35", _metric(result.ma35)), ("ma45", _metric(result.ma45))),
        availability,
        actions,
        _main_rise_hints(identity, product_bar, result),
    )
    return frame, result.state, tuple(diagnostics)


def replay_strategy(
    identity: ProductIdentity, bars: tuple[ProductBar, ...]
) -> StrategyReplay:
    """Replay one strategy, resetting all state at each authoritative segment."""
    inputs = tuple(bars)
    _validate_inputs(identity, inputs)
    frames: list[StrategyFrame] = []
    diagnostics: list[str] = []
    current_segment: str | None = None
    pairing = _PairingState()
    trend_state = initial_trend_band_state()
    escape_state = initial_escape_state()
    oscillation_state = OscillationState()
    main_rise_state = initial_main_rise_state()

    for product_bar in inputs:
        if product_bar.bar.segment_id != current_segment:
            current_segment = product_bar.bar.segment_id
            pairing = _PairingState()
            trend_state = initial_trend_band_state()
            escape_state = initial_escape_state()
            oscillation_state = OscillationState()
            main_rise_state = initial_main_rise_state()
        if identity.strategy is ProductStrategy.TREND:
            frame, trend_state, escape_state, found = _trend_frame(
                identity, product_bar, trend_state, escape_state, pairing
            )
        elif identity.strategy is ProductStrategy.OSCILLATION:
            frame, oscillation_state, found = _oscillation_frame(
                identity, product_bar, oscillation_state, pairing
            )
        else:
            frame, main_rise_state, found = _main_rise_frame(
                identity, product_bar, main_rise_state, pairing
            )
        frames.append(frame)
        diagnostics.extend(found)

    frame_tuple = tuple(frames)
    return StrategyReplay(
        identity,
        frame_tuple,
        tuple(action for frame in frame_tuple for action in frame.actions),
        tuple(hint for frame in frame_tuple for hint in frame.hints),
        tuple(dict.fromkeys(diagnostics)),
    )
