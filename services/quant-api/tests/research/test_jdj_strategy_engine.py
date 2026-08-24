from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
import importlib
import importlib.util
from types import ModuleType

import pytest

from app.market_data.domain import BarFrequency, CanonicalBar, ResolvedContractSegment
from app.research.jdj.jdj_context import JdjBarContext
from app.research.jdj.jdj_events import (
    JdjDirection,
    JdjKeyLevelBreakoutTriggerEvent,
    JdjSetupKind,
    JdjTrendFollowTriggerEvent,
    JdjTrendReentryTriggerEvent,
    JdjTriggerEvent,
)
from app.research.jdj_strategy.contract import JdjV1Config, load_jdj_v1_config
from app.research.n_structure.n_structure_state import NStructureKind
from app.research.n_structure.n_structure_swing import NSwingPivot, NSwingPivotKind


_CONTRACT = "JM2701"
_SEGMENT_START = date(2026, 8, 19)
_DAY = date(2026, 8, 19)
_START = datetime(2026, 8, 19, 1, 0, tzinfo=UTC)
_MULTIPLIER = Decimal("10")


def _modules() -> tuple[ModuleType, ModuleType]:
    engine_name = "app.research.jdj_strategy.engine"
    replay_name = "app.research.jdj_strategy.replay"
    assert importlib.util.find_spec(engine_name) is not None
    assert importlib.util.find_spec(replay_name) is not None
    return importlib.import_module(engine_name), importlib.import_module(replay_name)


def _bar(
    index: int,
    *,
    open_: str | int = 100,
    high: str | int = 100,
    low: str | int = 100,
    close: str | int = 100,
    trading_day: date = _DAY,
    bar_end: datetime | None = None,
) -> CanonicalBar:
    return CanonicalBar(
        bar_end=bar_end or _START + timedelta(minutes=index),
        trading_day=trading_day,
        open=Decimal(str(open_)),
        high=Decimal(str(high)),
        low=Decimal(str(low)),
        close=Decimal(str(close)),
        volume=Decimal("100"),
        turnover=None,
        open_interest=None,
    )


def _pivot(
    kind: NSwingPivotKind,
    price: str | int,
    *,
    confirmed_at: datetime,
    contract: str = _CONTRACT,
    segment_start: date = _SEGMENT_START,
) -> NSwingPivot:
    pivot_at = confirmed_at - timedelta(minutes=5)
    pivot_id = ":".join(
        (
            contract,
            segment_start.isoformat(),
            "5m",
            "0",
            kind.value,
            pivot_at.isoformat(),
        )
    )
    return NSwingPivot(
        pivot_id=pivot_id,
        epoch=0,
        kind=kind,
        source_timeframe=BarFrequency.M5,
        pivot_time=pivot_at,
        confirmed_at=confirmed_at,
        price=Decimal(str(price)),
        contract=contract,
        segment_start_trading_day=segment_start,
    )


def _context(
    bar: CanonicalBar,
    *,
    ema20: str | int | None = 90,
    trend: NStructureKind = NStructureKind.BULL,
    target: str | int | None = 110,
    direction: JdjDirection = JdjDirection.LONG,
    fact_boundary: datetime | None = None,
    first_of_day: bool = False,
    contract: str = _CONTRACT,
    segment_start: date = _SEGMENT_START,
) -> JdjBarContext:
    if first_of_day or bar.bar_end == _START:
        return JdjBarContext(
            bar=bar,
            ema20=Decimal(str(ema20)) if ema20 is not None else None,
            trend_kind=NStructureKind.UNDEFINED,
            trend_snapshot_observed_at=None,
            trend_epoch=None,
            eligible_high_pivot=None,
            eligible_low_pivot=None,
        )
    snapshot_at = fact_boundary or bar.bar_end - timedelta(minutes=1)
    pivot = (
        _pivot(
            NSwingPivotKind.HIGH
            if direction is JdjDirection.LONG
            else NSwingPivotKind.LOW,
            target,
            confirmed_at=snapshot_at,
            contract=contract,
            segment_start=segment_start,
        )
        if target is not None
        else None
    )
    return JdjBarContext(
        bar=bar,
        ema20=Decimal(str(ema20)) if ema20 is not None else None,
        trend_kind=trend,
        trend_snapshot_observed_at=snapshot_at,
        trend_epoch=0,
        eligible_high_pivot=(
            pivot if pivot is not None and pivot.kind is NSwingPivotKind.HIGH else None
        ),
        eligible_low_pivot=(
            pivot if pivot is not None and pivot.kind is NSwingPivotKind.LOW else None
        ),
    )


def _decimal_id(value: Decimal) -> str:
    return format(value.normalize(), "f")


def _trend_follow(
    bars: tuple[CanonicalBar, ...],
    observed_index: int,
    *,
    direction: JdjDirection = JdjDirection.LONG,
    reaction_index: int | None = None,
    observation_close: str | int | None = None,
) -> JdjTrendFollowTriggerEvent:
    reaction = bars[reaction_index if reaction_index is not None else observed_index - 1]
    observed = bars[observed_index]
    close = Decimal(
        str(observation_close if observation_close is not None else observed.close)
    )
    trigger = close
    candidate_id = "jdj_trend_follow_1m_candidate_v1"
    event_id = "|".join(
        (
            candidate_id,
            "jm",
            _CONTRACT,
            _SEGMENT_START.isoformat(),
            direction.value,
            reaction.bar_end.isoformat(),
            observed.bar_end.isoformat(),
            _decimal_id(trigger),
        )
    )
    return JdjTrendFollowTriggerEvent(
        event_id=event_id,
        source_kind="jdj_1m",
        setup_kind=JdjSetupKind.TREND_FOLLOW,
        candidate_id=candidate_id,
        source_event_kind="jdj_trend_follow_triggered",
        direction=direction,
        symbol="jm",
        contract=_CONTRACT,
        segment_start_trading_day=_SEGMENT_START,
        trading_day=observed.trading_day,
        observed_at=observed.bar_end,
        segment_bar_index=observed_index + 1,
        trend_snapshot_observed_at=reaction.bar_end - timedelta(minutes=1),
        reaction_at=reaction.bar_end,
        ema20_at_reaction=Decimal("100"),
        trigger_level=trigger,
        observation_close=close,
    )


def _reentry(
    bars: tuple[CanonicalBar, ...],
    observed_index: int,
    *,
    direction: JdjDirection = JdjDirection.LONG,
    excursion_extreme: str | int = 95,
    observation_close: str | int | None = None,
) -> JdjTrendReentryTriggerEvent:
    observed = bars[observed_index]
    close = Decimal(
        str(observation_close if observation_close is not None else observed.close)
    )
    trigger = close
    excursion_started_at = bars[observed_index - 3].bar_end
    reclaimed_at = bars[observed_index - 2].bar_end
    reaction_at = bars[observed_index - 1].bar_end
    extreme = Decimal(str(excursion_extreme))
    candidate_id = "jdj_trend_reentry_6_1m_candidate_v1"
    event_id = "|".join(
        (
            candidate_id,
            "jm",
            _CONTRACT,
            _SEGMENT_START.isoformat(),
            direction.value,
            excursion_started_at.isoformat(),
            _decimal_id(extreme),
            reclaimed_at.isoformat(),
            reaction_at.isoformat(),
            observed.bar_end.isoformat(),
            _decimal_id(trigger),
        )
    )
    return JdjTrendReentryTriggerEvent(
        event_id=event_id,
        source_kind="jdj_1m",
        setup_kind=JdjSetupKind.TREND_REENTRY_6,
        candidate_id=candidate_id,
        source_event_kind="jdj_trend_reentry_6_triggered",
        direction=direction,
        symbol="jm",
        contract=_CONTRACT,
        segment_start_trading_day=_SEGMENT_START,
        trading_day=observed.trading_day,
        observed_at=observed.bar_end,
        segment_bar_index=observed_index + 1,
        trend_snapshot_observed_at=reaction_at - timedelta(minutes=1),
        excursion_started_at=excursion_started_at,
        excursion_extreme=extreme,
        reclaimed_at=reclaimed_at,
        reaction_at=reaction_at,
        trigger_level=trigger,
        observation_close=close,
    )


def _key_level(
    bars: tuple[CanonicalBar, ...],
    observed_index: int,
    *,
    direction: JdjDirection = JdjDirection.LONG,
    key_level_price: str | int = 95,
    observation_close: str | int | None = None,
    contract: str = _CONTRACT,
    segment_start: date = _SEGMENT_START,
) -> JdjKeyLevelBreakoutTriggerEvent:
    observed = bars[observed_index]
    close = Decimal(
        str(observation_close if observation_close is not None else observed.close)
    )
    trigger = close
    confirmed_at = bars[observed_index - 3].bar_end - timedelta(minutes=1)
    first_break_at = bars[observed_index - 2].bar_end
    retest_at = bars[observed_index - 1].bar_end
    pivot_at = confirmed_at - timedelta(minutes=5)
    pivot_kind = "high" if direction is JdjDirection.LONG else "low"
    pivot_id = ":".join(
        (
            contract,
            segment_start.isoformat(),
            "5m",
            "0",
            pivot_kind,
            pivot_at.isoformat(),
        )
    )
    level = Decimal(str(key_level_price))
    candidate_id = "jdj_key_level_breakout_1m_candidate_v1"
    event_id = "|".join(
        (
            candidate_id,
            "jm",
            contract,
            segment_start.isoformat(),
            direction.value,
            "0",
            pivot_id,
            _decimal_id(level),
            confirmed_at.isoformat(),
            first_break_at.isoformat(),
            retest_at.isoformat(),
            observed.bar_end.isoformat(),
            _decimal_id(trigger),
        )
    )
    return JdjKeyLevelBreakoutTriggerEvent(
        event_id=event_id,
        source_kind="jdj_1m",
        setup_kind=JdjSetupKind.KEY_LEVEL_BREAKOUT,
        candidate_id=candidate_id,
        source_event_kind="jdj_key_level_breakout_triggered",
        direction=direction,
        symbol="jm",
        contract=contract,
        segment_start_trading_day=segment_start,
        trading_day=observed.trading_day,
        observed_at=observed.bar_end,
        segment_bar_index=observed_index + 1,
        trend_snapshot_observed_at=retest_at - timedelta(minutes=1),
        trend_epoch=0,
        key_level_pivot_id=pivot_id,
        key_level_price=level,
        key_level_confirmed_at=confirmed_at,
        first_break_at=first_break_at,
        retest_at=retest_at,
        trigger_level=trigger,
        observation_close=close,
    )


def _run(
    bars: tuple[CanonicalBar, ...],
    events: tuple[JdjTriggerEvent, ...],
    *,
    symbol: str = "jm",
    segment: ResolvedContractSegment | None = None,
    contexts: tuple[JdjBarContext, ...] | None = None,
    config: JdjV1Config | None = None,
    multiplier: Decimal = _MULTIPLIER,
    terminal_by_day: dict[date, datetime] | None = None,
):
    _, replay = _modules()
    if contexts is None:
        built_contexts: list[JdjBarContext] = []
        previous: CanonicalBar | None = None
        segment_contract = events[0].contract if events else _CONTRACT
        segment_start = (
            events[0].segment_start_trading_day if events else _SEGMENT_START
        )
        for bar in bars:
            first_of_day = previous is None or previous.trading_day != bar.trading_day
            built_contexts.append(
                _context(
                    bar,
                    fact_boundary=previous.bar_end if not first_of_day else None,
                    first_of_day=first_of_day,
                    contract=segment_contract,
                    segment_start=segment_start,
                )
            )
            previous = bar
        supplied_contexts = tuple(built_contexts)
    else:
        supplied_contexts = contexts
    resolved_segment = segment or ResolvedContractSegment(
        contract=events[0].contract if events else _CONTRACT,
        start_trading_day=(
            events[0].segment_start_trading_day if events else _SEGMENT_START
        ),
        end_trading_day=max(bar.trading_day for bar in bars),
    )
    return replay.run_jdj_reference_segment(
        symbol=symbol,
        segment=resolved_segment,
        bars_1m=bars,
        contexts=supplied_contexts,
        candidate_events=events,
        contract_multiplier=multiplier,
        terminal_bar_end_by_day=(
            terminal_by_day
            if terminal_by_day is not None
            else {bars[-1].trading_day: bars[-1].bar_end}
        ),
        config=config or load_jdj_v1_config(),
    )


def _actions(replay, kind: str):  # type: ignore[no-untyped-def]
    return tuple(action for action in replay.actions if action.kind.value == kind)


def _contexts_without_pivots(
    bars: tuple[CanonicalBar, ...],
) -> tuple[JdjBarContext, ...]:
    return tuple(
        JdjBarContext(
            bar=bar,
            ema20=Decimal("100"),
            trend_kind=NStructureKind.UNDEFINED,
            trend_snapshot_observed_at=None,
            trend_epoch=None,
            eligible_high_pivot=None,
            eligible_low_pivot=None,
        )
        for bar in bars
    )


def test_no_event_no_pivot_replay_uses_explicit_segment_identity() -> None:
    _, replay = _modules()
    bars = tuple(_bar(index) for index in range(3))
    segment = ResolvedContractSegment(
        contract="JM2701",
        start_trading_day=_SEGMENT_START,
        end_trading_day=_DAY,
    )

    result = replay.run_jdj_reference_segment(
        symbol="jm",
        segment=segment,
        bars_1m=bars,
        contexts=_contexts_without_pivots(bars),
        candidate_events=(),
        contract_multiplier=_MULTIPLIER,
        terminal_bar_end_by_day={_DAY: bars[-1].bar_end},
        config=load_jdj_v1_config(),
    )

    assert result.actions == ()


@pytest.mark.parametrize("symbol", ("", "JM", " jm", "jm "))
def test_explicit_symbol_must_be_nonempty_normalized_lowercase(symbol: str) -> None:
    _, replay = _modules()
    bars = tuple(_bar(index) for index in range(3))

    with pytest.raises(replay.JdjStrategyReplayError):
        _run(
            bars,
            (),
            symbol=symbol,
            contexts=_contexts_without_pivots(bars),
        )


def test_explicit_segment_must_be_resolved_contract_segment() -> None:
    _, replay = _modules()
    bars = tuple(_bar(index) for index in range(3))

    with pytest.raises(replay.JdjStrategyReplayError):
        _run(
            bars,
            (),
            segment=object(),  # type: ignore[arg-type]
            contexts=_contexts_without_pivots(bars),
        )


def test_event_symbol_must_match_explicit_symbol() -> None:
    _, replay = _modules()
    bars = tuple(_bar(index) for index in range(6))
    event = _key_level(bars, 3)

    with pytest.raises(replay.JdjStrategyReplayError):
        _run(
            bars,
            (event,),
            symbol="rb",
            contexts=_contexts_without_pivots(bars),
        )


def test_event_contract_must_match_explicit_segment() -> None:
    _, replay = _modules()
    bars = tuple(_bar(index) for index in range(6))
    event = _key_level(bars, 3)
    segment = ResolvedContractSegment("JM2705", _SEGMENT_START, _DAY)

    with pytest.raises(replay.JdjStrategyReplayError):
        _run(
            bars,
            (event,),
            segment=segment,
            contexts=_contexts_without_pivots(bars),
        )


def test_event_segment_start_must_match_explicit_segment() -> None:
    _, replay = _modules()
    bars = tuple(_bar(index) for index in range(6))
    event = _key_level(bars, 3)
    segment = ResolvedContractSegment(
        _CONTRACT,
        _SEGMENT_START - timedelta(days=1),
        _DAY,
    )

    with pytest.raises(replay.JdjStrategyReplayError):
        _run(
            bars,
            (event,),
            segment=segment,
            contexts=_contexts_without_pivots(bars),
        )


@pytest.mark.parametrize(
    "segment",
    (
        ResolvedContractSegment(
            _CONTRACT,
            _DAY + timedelta(days=1),
            _DAY + timedelta(days=2),
        ),
        ResolvedContractSegment(
            _CONTRACT,
            _DAY - timedelta(days=2),
            _DAY - timedelta(days=1),
        ),
    ),
)
def test_bars_must_stay_inside_explicit_segment_window(
    segment: ResolvedContractSegment,
) -> None:
    _, replay = _modules()
    bars = tuple(_bar(index) for index in range(3))

    with pytest.raises(replay.JdjStrategyReplayError):
        _run(
            bars,
            (),
            segment=segment,
            contexts=_contexts_without_pivots(bars),
        )


@pytest.mark.parametrize(
    "terminal_by_day",
    (
        {},
        {
            _DAY: _START + timedelta(minutes=2),
            _DAY + timedelta(days=1): _START + timedelta(minutes=2),
        },
    ),
)
def test_terminal_day_set_must_exactly_match_bar_days(
    terminal_by_day: dict[date, datetime],
) -> None:
    _, replay = _modules()
    bars = tuple(_bar(index) for index in range(3))

    with pytest.raises(replay.JdjStrategyReplayError):
        _run(
            bars,
            (),
            contexts=_contexts_without_pivots(bars),
            terminal_by_day=terminal_by_day,
        )


def test_same_bar_setups_collapse_to_key_level_primary_with_causal_stop() -> None:
    bars = tuple(
        _bar(i, high=101 if i < 3 else 111, low=94 if i == 2 else 99, close=100)
        for i in range(6)
    )
    events = (
        _trend_follow(bars, 3, reaction_index=2),
        _reentry(bars, 3, excursion_extreme=94),
        _key_level(bars, 3, key_level_price=95),
    )

    result = _run(bars, events)

    entries = _actions(result, "entry")
    assert len(entries) == 1
    assert entries[0].primary_setup == "key_level_breakout"
    assert entries[0].supporting_setups == ("trend_reentry_6", "trend_follow")
    assert entries[0].source_event_ids == tuple(event.event_id for event in events[::-1])
    assert entries[0].stop_price == Decimal("95")


def test_opposite_directions_on_one_decision_bar_are_rejected() -> None:
    bars = tuple(_bar(i, high=111, low=89, close=100) for i in range(6))
    events = (
        _trend_follow(bars, 3, direction=JdjDirection.LONG),
        _trend_follow(bars, 3, direction=JdjDirection.SHORT),
    )

    result = _run(bars, events)

    assert not _actions(result, "entry")
    rejected = _actions(result, "rejected")
    assert len(rejected) == 1
    assert rejected[0].reason == "AMBIGUOUS_DIRECTION"
    assert rejected[0].source_event_ids == tuple(event.event_id for event in events)


@pytest.mark.parametrize(
    ("event_kind", "expected_stop"),
    (("trend_follow", "96"), ("trend_reentry_6", "94"), ("key_level_breakout", "95")),
)
def test_each_setup_resolves_its_own_frozen_structural_stop(
    event_kind: str,
    expected_stop: str,
) -> None:
    bars = tuple(
        _bar(i, high=106 if i == 2 else 112, low=96 if i == 2 else 99, close=100)
        for i in range(6)
    )
    factories = {
        "trend_follow": lambda: _trend_follow(bars, 3, reaction_index=2),
        "trend_reentry_6": lambda: _reentry(bars, 3, excursion_extreme=94),
        "key_level_breakout": lambda: _key_level(bars, 3, key_level_price=95),
    }

    contexts = tuple(_context(bar, target=112) for bar in bars)
    result = _run(bars, (factories[event_kind](),), contexts=contexts)

    assert _actions(result, "entry")[0].stop_price == Decimal(expected_stop)


def test_target_must_be_known_and_reward_risk_must_reach_two() -> None:
    bars = tuple(_bar(i, high=100, low=100, close=100) for i in range(6))
    event = _key_level(bars, 3, key_level_price=95)
    no_target = tuple(_context(bar, target=None) for bar in bars)
    too_close_target = tuple(_context(bar, target=108) for bar in bars)

    missing = _run(bars, (event,), contexts=no_target)
    low_rr = _run(bars, (event,), contexts=too_close_target)

    assert _actions(missing, "rejected")[0].reason == "TARGET_UNAVAILABLE"
    assert _actions(low_rr, "rejected")[0].reason == "REWARD_RISK_BELOW_MINIMUM"
    assert _actions(low_rr, "rejected")[0].reward_risk == Decimal("1.6")


def test_future_confirmed_pivot_fails_closed() -> None:
    _, replay = _modules()
    bars = tuple(_bar(i) for i in range(6))
    contexts = list(_context(bar, target=None) for bar in bars)
    decision = bars[3]
    future_pivot = _pivot(
        NSwingPivotKind.HIGH,
        110,
        confirmed_at=decision.bar_end + timedelta(minutes=1),
    )
    contexts[3] = JdjBarContext(
        bar=decision,
        ema20=Decimal("90"),
        trend_kind=NStructureKind.BULL,
        trend_snapshot_observed_at=decision.bar_end - timedelta(minutes=1),
        trend_epoch=0,
        eligible_high_pivot=future_pivot,
        eligible_low_pivot=None,
    )
    event = _key_level(bars, 3, key_level_price=95)

    with pytest.raises(replay.JdjStrategyReplayError):
        _run(bars, (event,), contexts=tuple(contexts))


@pytest.mark.parametrize("invalid_fact", ("same_boundary_pivot", "future_snapshot"))
def test_context_causality_violations_fail_closed(invalid_fact: str) -> None:
    _, replay = _modules()
    bars = tuple(_bar(i) for i in range(6))
    contexts = list(_context(bar, target=None) for bar in bars)
    decision = bars[3]
    pivot = (
        _pivot(NSwingPivotKind.HIGH, 110, confirmed_at=decision.bar_end)
        if invalid_fact == "same_boundary_pivot"
        else None
    )
    contexts[3] = JdjBarContext(
        bar=decision,
        ema20=Decimal("90"),
        trend_kind=NStructureKind.BULL,
        trend_snapshot_observed_at=(
            decision.bar_end + timedelta(minutes=1)
            if invalid_fact == "future_snapshot"
            else decision.bar_end - timedelta(minutes=1)
        ),
        trend_epoch=0,
        eligible_high_pivot=pivot,
        eligible_low_pivot=None,
    )
    event = _key_level(bars, 3, key_level_price=95)

    with pytest.raises(replay.JdjStrategyReplayError):
        _run(bars, (event,), contexts=tuple(contexts))


@pytest.mark.parametrize("identity_drift", ("contract", "segment"))
def test_cross_segment_context_facts_fail_closed(identity_drift: str) -> None:
    _, replay = _modules()
    bars = tuple(_bar(i) for i in range(6))
    contexts = list(_context(bar, target=None) for bar in bars)
    decision = bars[3]
    contexts[3] = JdjBarContext(
        bar=decision,
        ema20=Decimal("90"),
        trend_kind=NStructureKind.BULL,
        trend_snapshot_observed_at=decision.bar_end - timedelta(minutes=1),
        trend_epoch=0,
        eligible_high_pivot=_pivot(
            NSwingPivotKind.HIGH,
            110,
            confirmed_at=bars[2].bar_end,
            contract="JM2705" if identity_drift == "contract" else _CONTRACT,
            segment_start=(
                date(2026, 8, 18)
                if identity_drift == "segment"
                else _SEGMENT_START
            ),
        ),
        eligible_low_pivot=None,
    )
    event = _key_level(bars, 3, key_level_price=95)

    with pytest.raises(replay.JdjStrategyReplayError):
        _run(bars, (event,), contexts=tuple(contexts))


@pytest.mark.parametrize(
    ("direction", "next_open", "next_high", "next_low", "expected_price", "basis"),
    (
        (JdjDirection.LONG, "99", "101", "98", "99", "better_open"),
        (JdjDirection.LONG, "101", "102", "99.5", "100", "limit_touch"),
        (JdjDirection.SHORT, "101", "102", "99", "101", "better_open"),
        (JdjDirection.SHORT, "99", "100.5", "98", "100", "limit_touch"),
    ),
)
def test_one_bar_limit_fills_at_better_open_or_limit_touch(
    direction: JdjDirection,
    next_open: str,
    next_high: str,
    next_low: str,
    expected_price: str,
    basis: str,
) -> None:
    stop = 95 if direction is JdjDirection.LONG else 105
    target = 110 if direction is JdjDirection.LONG else 90
    trend = NStructureKind.BULL if direction is JdjDirection.LONG else NStructureKind.BEAR
    bars = (
        _bar(0),
        _bar(1),
            _bar(2, low=stop if direction is JdjDirection.LONG else 100, high=stop if direction is JdjDirection.SHORT else 100),
        _bar(3, close=100),
        _bar(4, open_=next_open, high=next_high, low=next_low, close=100),
        _bar(5),
    )
    contexts = tuple(
        _context(bar, trend=trend, target=target, direction=direction, ema20=90 if direction is JdjDirection.LONG else 110)
        for bar in bars
    )
    event = _key_level(bars, 3, direction=direction, key_level_price=stop)

    result = _run(bars, (event,), contexts=contexts)

    entry = _actions(result, "entry")[0]
    assert entry.reference_price == Decimal(expected_price)
    assert entry.fill_basis == basis
    assert entry.effective_bar_end == bars[4].bar_end


@pytest.mark.parametrize(
    ("direction", "next_high", "next_low"),
    ((JdjDirection.LONG, "101", "100.5"), (JdjDirection.SHORT, "99.5", "99")),
)
def test_unfilled_entry_expires_after_one_bar_and_never_creates_episode(
    direction: JdjDirection,
    next_high: str,
    next_low: str,
) -> None:
    stop = 95 if direction is JdjDirection.LONG else 105
    target = 110 if direction is JdjDirection.LONG else 90
    trend = NStructureKind.BULL if direction is JdjDirection.LONG else NStructureKind.BEAR
    bars = tuple(_bar(i) for i in range(3)) + (
        _bar(3, close=100),
        _bar(
            4,
            open_=101 if direction is JdjDirection.LONG else 99,
            high=next_high,
            low=next_low,
            close=101 if direction is JdjDirection.LONG else 99,
        ),
        _bar(5, open_=100, high=101, low=99, close=100),
    )
    contexts = tuple(
        _context(bar, trend=trend, target=target, direction=direction, ema20=90 if direction is JdjDirection.LONG else 110)
        for bar in bars
    )
    event = _key_level(bars, 3, direction=direction, key_level_price=stop)

    result = _run(bars, (event,), contexts=contexts)

    assert not _actions(result, "entry")
    expired = _actions(result, "rejected")[0]
    assert expired.reason == "ENTRY_LIMIT_EXPIRED"
    assert expired.episode_id is None
    assert expired.effective_bar_end == bars[4].bar_end


def test_reference_quantity_uses_admissible_worst_price_and_entry_is_deterministic() -> None:
    bars = tuple(_bar(i, high=110, low=95, close=100) for i in range(6))
    event = _key_level(bars, 3, key_level_price=95)

    first = _run(bars, (event,))
    second = _run(bars, (event,))

    entry = _actions(first, "entry")[0]
    assert entry.reference_price == Decimal("100")
    assert entry.quantity == 100
    assert entry.position_quantity_after == 100
    assert entry.episode_id is not None
    assert entry.episode_id == _actions(second, "entry")[0].episode_id
    assert entry.reward_risk == Decimal("2")


def test_planned_episode_risk_above_one_percent_is_rejected() -> None:
    bars = tuple(_bar(i, high=110, low=95, close=100) for i in range(6))
    event = _key_level(bars, 3, key_level_price=95)
    config = load_jdj_v1_config()
    oversized = replace(
        config,
        profile=replace(config.profile, base_risk_fraction=Decimal("0.02")),
    )

    result = _run(bars, (event,), config=oversized)

    assert not _actions(result, "entry")
    assert _actions(result, "rejected")[0].reason == "EPISODE_RISK_LIMIT"


def test_duplicate_source_is_consumed_only_once() -> None:
    bars = tuple(_bar(i, high=110, low=95, close=100) for i in range(6))
    event = _key_level(bars, 3, key_level_price=95)

    result = _run(bars, (event, event))

    assert len(_actions(result, "entry")) == 1
    assert _actions(result, "entry")[0].source_event_ids == (event.event_id,)


def test_source_less_fill_action_ids_include_episode_segment_identity() -> None:
    action_ids_by_identity: list[dict[str, str]] = []
    for contract, segment_start in (
        ("JM2701", _SEGMENT_START),
        ("JM2705", date(2026, 8, 18)),
    ):
        bars = (
            _bar(0),
            _bar(1),
            _bar(2),
            _bar(3, close=100),
            _bar(4, open_=100, high=101, low=99, close=100),
            _bar(5, open_=110, high=111, low=109, close=110),
            _bar(6, open_=110, high=111, low=109, close=110),
            _bar(7, open_=101, high=102, low=100, close=101),
            _bar(8, open_=101, high=102, low=100, close=101),
        )
        event = _key_level(
            bars,
            3,
            key_level_price=95,
            contract=contract,
            segment_start=segment_start,
        )

        result = _run(bars, (event,), multiplier=Decimal("100"))

        action_ids_by_identity.append(
            {
                kind: _actions(result, kind)[0].event_id
                for kind in ("reduce", "exit")
            }
        )

    for kind in ("reduce", "exit"):
        first = action_ids_by_identity[0][kind]
        second = action_ids_by_identity[1][kind]
        assert first.startswith("jdj-action-")
        assert second.startswith("jdj-action-")
        assert first != second


def test_first_target_close_reduces_forty_percent_at_next_open_and_moves_stop() -> None:
    bars = (
        _bar(0),
        _bar(1),
        _bar(2),
        _bar(3, close=100),
        _bar(4, open_=100, high=101, low=99, close=100),
        _bar(5, open_=104, high=110, low=103, close=110),
        _bar(6, open_=112, high=113, low=111, close=112),
        _bar(7),
    )
    event = _key_level(bars, 3, key_level_price=95)

    result = _run(bars, (event,), multiplier=Decimal("100"))

    entry = _actions(result, "entry")[0]
    reduce = _actions(result, "reduce")[0]
    assert entry.quantity == 10
    assert reduce.decision_at == bars[5].bar_end
    assert reduce.effective_bar_end == bars[6].bar_end
    assert reduce.reference_price == Decimal("112")
    assert reduce.quantity == 4
    assert reduce.position_quantity_after == 6
    assert reduce.stop_price == Decimal("100")
    assert reduce.reason == "TARGET_1_PARTIAL_PROFIT"


def test_partial_profit_floor_zero_produces_no_fake_reduce() -> None:
    bars = (
        _bar(0), _bar(1), _bar(2), _bar(3, close=100),
        _bar(4, open_=100, high=101, low=99, close=100),
        _bar(5, open_=110, high=111, low=109, close=110),
        _bar(6),
    )
    event = _key_level(bars, 3, key_level_price=95)

    result = _run(bars, (event,), multiplier=Decimal("1000"))

    assert _actions(result, "entry")[0].quantity == 1
    assert not _actions(result, "reduce")


def test_add_requires_actual_profitable_partial_exit() -> None:
    bars = tuple(_bar(i, high=110, low=95, close=100) for i in range(8))
    entry_event = _key_level(bars, 3, key_level_price=95)
    add_event = _trend_follow(bars, 5, reaction_index=4)

    result = _run(bars, (entry_event, add_event))

    assert not _actions(result, "add")
    assert any(action.reason == "ADD_PARTIAL_PROFIT_REQUIRED" for action in _actions(result, "rejected"))


def test_two_fresh_profitable_trend_follow_events_add_twenty_five_percent() -> None:
    bars = (
        _bar(0), _bar(1), _bar(2), _bar(3, close=100),
        _bar(4, open_=100, high=101, low=99, close=100),
        _bar(5, open_=110, high=111, low=109, close=110),
        _bar(6, open_=112, high=113, low=111, close=112),
        _bar(7, open_=105, high=106, low=104, close=105),
        _bar(8, open_=102, high=106, low=102, close=105),
        _bar(9, open_=106, high=107, low=105, close=106),
        _bar(10, open_=103, high=107, low=103, close=106),
        _bar(11),
    )
    entry = _key_level(bars, 3, key_level_price=95)
    add_one = _trend_follow(bars, 7, reaction_index=6, observation_close=105)
    add_two = _trend_follow(bars, 9, reaction_index=8, observation_close=106)

    result = _run(bars, (entry, add_one, add_two), multiplier=Decimal("100"))

    adds = _actions(result, "add")
    assert [action.quantity for action in adds] == [1, 1]
    assert [action.position_quantity_after for action in adds] == [7, 8]
    assert all(action.stop_price is not None for action in adds)
    assert adds[0].stop_price == adds[0].reference_price * Decimal("1") / Decimal("7") + Decimal("600") / Decimal("7")
    assert adds[1].stop_price == adds[1].reference_price * Decimal("1") / Decimal("8") + adds[0].stop_price * Decimal("7") / Decimal("8")


def test_mixed_same_bar_setup_selects_fresh_trend_follow_as_add_source() -> None:
    bars = (
        _bar(0),
        _bar(1),
        _bar(2),
        _bar(3, close=100),
        _bar(4, open_=100, high=101, low=99, close=100),
        _bar(5, open_=110, high=111, low=109, close=110),
        _bar(6, open_=112, high=113, low=111, close=112),
        _bar(7, open_=105, high=106, low=104, close=105),
        _bar(8, open_=102, high=106, low=102, close=105),
        _bar(9),
    )
    entry = _key_level(bars, 3, key_level_price=95)
    add_source = _trend_follow(
        bars,
        7,
        reaction_index=6,
        observation_close=105,
    )
    competing_setup = _key_level(
        bars,
        7,
        key_level_price=95,
        observation_close=105,
    )

    result = _run(
        bars,
        (entry, competing_setup, add_source),
        multiplier=Decimal("100"),
    )

    add = _actions(result, "add")[0]
    assert add.source_event_ids == (add_source.event_id,)
    assert add.primary_setup == "trend_follow"
    rejected = _actions(result, "rejected")
    assert any(
        action.source_event_ids == (competing_setup.event_id,)
        and action.reason == "OPEN_EPISODE_EVENT_REJECTED"
        for action in rejected
    )


def test_third_add_and_opposite_or_repeated_sources_are_rejected() -> None:
    bars = tuple(_bar(i, high=110, low=95, close=100) for i in range(15))
    # Force a profitable partial before add candidates.
    changed = list(bars)
    changed[5] = _bar(5, open_=110, high=111, low=109, close=110)
    changed[6] = _bar(6, open_=110, high=111, low=109, close=110)
    for index in range(7, 15):
        changed[index] = _bar(index, open_=101, high=110, low=100, close=101)
    bars = tuple(changed)
    entry = _key_level(bars, 3, key_level_price=95)
    add_one = _trend_follow(bars, 7, reaction_index=6)
    add_two = _trend_follow(bars, 9, reaction_index=8)
    add_three = _trend_follow(bars, 11, reaction_index=10)
    opposite = _trend_follow(
        bars,
        12,
        direction=JdjDirection.SHORT,
        reaction_index=11,
    )

    result = _run(bars, (entry, add_one, add_two, add_three, opposite, add_two), multiplier=Decimal("100"))

    reasons = {action.reason for action in _actions(result, "rejected")}
    assert "ADD_COUNT_LIMIT" in reasons
    assert "OPEN_EPISODE_EVENT_REJECTED" in reasons
    assert len(_actions(result, "add")) == 2


@pytest.mark.parametrize(
    ("bars", "contexts", "reason"),
    (
        (
            tuple(_bar(i, low=94 if i == 5 else 99, close=94 if i == 5 else 100) for i in range(8)),
            None,
            "PROTECTIVE_STOP_CROSSED",
        ),
        (
            tuple(_bar(i, close=94 if i == 5 else 100, low=94 if i == 5 else 99) for i in range(8)),
            "ema",
            "EMA20_LOST",
        ),
        (
            tuple(_bar(i) for i in range(8)),
            "trend",
            "TREND_CONTEXT_LOST",
        ),
    ),
)
def test_completed_close_exit_conditions_fill_only_at_next_open(
    bars: tuple[CanonicalBar, ...],
    contexts: str | None,
    reason: str,
) -> None:
    supplied = tuple(_context(bar) for bar in bars)
    if contexts == "ema":
        supplied = tuple(_context(bar, ema20=95, target=120) for bar in bars)
    elif contexts == "trend":
        supplied = tuple(
            _context(bar, trend=NStructureKind.RANGE if index == 5 else NStructureKind.BULL)
            for index, bar in enumerate(bars)
        )
    event = _key_level(
        bars,
        3,
        key_level_price=90 if contexts == "ema" else 95,
    )

    result = _run(bars, (event,), contexts=supplied)

    exit_action = _actions(result, "exit")[0]
    assert exit_action.reason == reason
    assert exit_action.decision_at == bars[5].bar_end
    assert exit_action.effective_bar_end == bars[6].bar_end
    assert exit_action.reference_price == bars[6].open


def test_intrabar_stop_touch_without_close_cross_does_not_exit() -> None:
    bars = tuple(
        _bar(i, low=94 if i == 5 else 99, close=96 if i == 5 else 100)
        for i in range(8)
    )
    event = _key_level(bars, 3, key_level_price=95)

    result = _run(bars, (event,))

    assert not any(
        action.reason == "PROTECTIVE_STOP_CROSSED"
        for action in _actions(result, "exit")
    )


def test_drawdown_pause_blocks_exactly_fifteen_subsequent_present_bars() -> None:
    bars = tuple(_bar(i) for i in range(4)) + (
        _bar(4, open_=100, high=101, low=99, close=100),
        _bar(5, open_=94.49, high=95, low=94, close=94.49),
    ) + tuple(
        _bar(6 + i, open_=100, high=101, low=99, close=100, bar_end=_START + timedelta(minutes=20 + i * 2))
        for i in range(17)
    )
    entry = _key_level(bars, 3, key_level_price=95)
    paused_events = tuple(_trend_follow(bars, index, reaction_index=index - 1) for index in range(6, 21))
    resume = _trend_follow(bars, 21, reaction_index=20)

    result = _run(bars, (entry, *paused_events, resume), multiplier=Decimal("100"))

    pauses = _actions(result, "daily_pause")
    assert len(pauses) == 1
    assert pauses[0].decision_at == bars[5].bar_end
    blocked = [action for action in _actions(result, "rejected") if action.reason == "DAILY_PAUSE_ACTIVE"]
    assert len(blocked) == 15
    assert any(action.decision_at == bars[21].bar_end for action in result.actions)


def test_exit_gap_pause_rejects_same_bar_candidate_without_shifting_fifteen_bar_window() -> None:
    bars = tuple(_bar(i) for i in range(6)) + (
        _bar(6, open_=94, high=95, low=94, close=94),
    ) + tuple(_bar(i) for i in range(7, 25))
    contexts = tuple(
        _context(
            bar,
            trend=NStructureKind.RANGE if index == 5 else NStructureKind.BULL,
            fact_boundary=bars[index - 1].bar_end if index > 0 else None,
            first_of_day=index == 0,
        )
        for index, bar in enumerate(bars)
    )
    entry = _key_level(bars, 3, key_level_price=95)
    trigger_bar_candidate = _trend_follow(bars, 6, reaction_index=5)
    paused_candidates = tuple(
        _trend_follow(bars, index, reaction_index=index - 1)
        for index in range(7, 22)
    )
    resume = _key_level(bars, 22, key_level_price=95)

    result = _run(
        bars,
        (entry, trigger_bar_candidate, *paused_candidates, resume),
        contexts=contexts,
    )

    pauses = _actions(result, "daily_pause")
    assert len(pauses) == 1
    assert pauses[0].decision_at == bars[6].bar_end
    rejected = [
        action
        for action in _actions(result, "rejected")
        if action.reason == "DAILY_PAUSE_ACTIVE"
    ]
    assert [action.decision_at for action in rejected] == [
        bars[index].bar_end for index in range(6, 22)
    ]
    entries = _actions(result, "entry")
    assert len(entries) == 2
    assert entries[0].effective_bar_end == bars[4].bar_end
    assert entries[1].decision_at == bars[22].bar_end
    assert entries[1].effective_bar_end == bars[23].bar_end
    assert not _actions(result, "add")


def test_one_percent_drawdown_stops_day_and_conservatively_exits() -> None:
    bars = tuple(_bar(i) for i in range(4)) + (
        _bar(4, open_=100, high=101, low=99, close=100),
        _bar(5, open_=89, high=90, low=89, close=89),
        _bar(6, open_=90, high=91, low=89, close=90),
        _bar(7),
    )
    event = _key_level(bars, 3, key_level_price=95)

    result = _run(bars, (event,), multiplier=Decimal("100"))

    stop = _actions(result, "daily_stop")[0]
    exit_action = _actions(result, "exit")[0]
    assert stop.decision_at == bars[5].bar_end
    assert exit_action.reason == "DAILY_STOP"
    assert exit_action.effective_bar_end == bars[6].bar_end


@pytest.mark.parametrize(
    ("gap_open", "daily_kind"),
    (("94", "daily_pause"), ("89", "daily_stop")),
)
def test_next_open_exit_gap_can_trigger_flat_daily_risk_action(
    gap_open: str,
    daily_kind: str,
) -> None:
    bars = (
        _bar(0),
        _bar(1),
        _bar(2),
        _bar(3, close=100),
        _bar(4, open_=100, high=101, low=99, close=100),
        _bar(5, open_=100, high=101, low=99, close=100),
        _bar(
            6,
            open_=gap_open,
            high=Decimal(gap_open) + Decimal("1"),
            low=gap_open,
            close=gap_open,
        ),
        _bar(7),
    )
    contexts = tuple(
        _context(
            bar,
            trend=(
                NStructureKind.RANGE
                if index == 5
                else NStructureKind.BULL
            ),
            fact_boundary=bars[index - 1].bar_end if index > 0 else None,
            first_of_day=index == 0,
        )
        for index, bar in enumerate(bars)
    )
    event = _key_level(bars, 3, key_level_price=95)

    result = _run(bars, (event,), contexts=contexts)

    exit_action = _actions(result, "exit")[0]
    daily_action = _actions(result, daily_kind)[0]
    assert exit_action.reason == "TREND_CONTEXT_LOST"
    assert exit_action.effective_bar_end == bars[6].bar_end
    assert daily_action.decision_at == bars[6].bar_end
    assert daily_action.position_quantity_after == 0
    assert daily_action.episode_id == exit_action.episode_id


@pytest.mark.parametrize(
    ("gap_open", "daily_kind"),
    (("94", "daily_pause"), ("89", "daily_stop")),
)
def test_daily_action_ids_include_episode_segment_identity(
    gap_open: str,
    daily_kind: str,
) -> None:
    action_ids: list[str] = []
    for contract, segment_start in (
        ("JM2701", _SEGMENT_START),
        ("JM2705", date(2026, 8, 18)),
    ):
        bars = (
            _bar(0),
            _bar(1),
            _bar(2),
            _bar(3, close=100),
            _bar(4, open_=100, high=101, low=99, close=100),
            _bar(5, open_=100, high=101, low=99, close=100),
            _bar(
                6,
                open_=gap_open,
                high=Decimal(gap_open) + Decimal("1"),
                low=gap_open,
                close=gap_open,
            ),
            _bar(7),
        )
        contexts = tuple(
            _context(
                bar,
                trend=(
                    NStructureKind.RANGE
                    if index == 5
                    else NStructureKind.BULL
                ),
                fact_boundary=bars[index - 1].bar_end if index > 0 else None,
                first_of_day=index == 0,
                contract=contract,
                segment_start=segment_start,
            )
            for index, bar in enumerate(bars)
        )
        event = _key_level(
            bars,
            3,
            key_level_price=95,
            contract=contract,
            segment_start=segment_start,
        )

        result = _run(bars, (event,), contexts=contexts)

        action_ids.append(_actions(result, daily_kind)[0].event_id)

    assert all(action_id.startswith("jdj-action-") for action_id in action_ids)
    assert action_ids[0] != action_ids[1]


def test_terminal_lead_blocks_entry_and_flattens_existing_position_at_final_open() -> None:
    bars = tuple(_bar(i, high=110, low=95, close=100) for i in range(7))
    entry = _key_level(bars, 3, key_level_price=95)
    too_late = _trend_follow(bars, 5, reaction_index=4)

    result = _run(bars, (entry, too_late))

    exits = _actions(result, "exit")
    assert exits[0].reason == "SESSION_FLATTEN"
    assert exits[0].decision_at == bars[5].bar_end
    assert exits[0].effective_bar_end == bars[6].bar_end
    assert any(action.reason == "SESSION_TERMINAL_GUARD" for action in _actions(result, "rejected"))


def test_intermediate_session_break_is_not_mistaken_for_terminal() -> None:
    bars = (
        _bar(0), _bar(1), _bar(2), _bar(3, close=100),
        _bar(4, open_=100, high=101, low=99, close=100),
        _bar(5, bar_end=_START + timedelta(hours=2)),
        _bar(6, bar_end=_START + timedelta(hours=2, minutes=1)),
    )
    event = _key_level(bars, 3, key_level_price=95)

    result = _run(bars, (event,))

    assert _actions(result, "entry")
    assert not any(action.decision_at == bars[4].bar_end and action.reason == "SESSION_FLATTEN" for action in result.actions)
