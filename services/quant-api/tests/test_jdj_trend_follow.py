from __future__ import annotations

from dataclasses import FrozenInstanceError, fields, replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from app.market_data.domain import BarFrequency, CanonicalBar
from app.research.jdj.jdj_context import JdjBarContext, JdjContextError
from app.research.jdj.jdj_events import (
    JdjDirection,
    JdjSetupKind,
    JdjTrendFollowTriggerEvent,
)
from app.research.jdj.jdj_trend_follow import (
    JdjTrendFollowTrace,
    reduce_jdj_trend_follow,
)
from app.research.n_structure.n_structure_state import NStructureKind
from app.research.n_structure.n_structure_swing import NSwingPivot, NSwingPivotKind


_SYMBOL = "jm"
_CONTRACT = "JM2701"
_SEGMENT_START = date(2026, 8, 3)
_TRADING_DAY = date(2026, 8, 19)
_NEXT_TRADING_DAY = date(2026, 8, 20)
_START = datetime(2026, 8, 19, 1, 1, tzinfo=UTC)


def _decimal(value: str | int) -> Decimal:
    return Decimal(str(value))


def _context_at(
    bar_end: datetime,
    *,
    high: str | int,
    low: str | int,
    close: str | int,
    ema20: str | int | None,
    trend: NStructureKind,
    trading_day: date = _TRADING_DAY,
    snapshot_at: datetime | None = None,
) -> JdjBarContext:
    high_value = _decimal(high)
    low_value = _decimal(low)
    close_value = _decimal(close)
    has_snapshot = trend is not NStructureKind.UNDEFINED
    observed_at = (
        snapshot_at
        if snapshot_at is not None
        else bar_end - timedelta(minutes=5)
    ) if has_snapshot else None
    return JdjBarContext(
        bar=CanonicalBar(
            bar_end=bar_end,
            trading_day=trading_day,
            open=close_value,
            high=high_value,
            low=low_value,
            close=close_value,
            volume=Decimal("100"),
            turnover=None,
            open_interest=None,
        ),
        ema20=_decimal(ema20) if ema20 is not None else None,
        trend_kind=trend,
        trend_snapshot_observed_at=observed_at,
        trend_epoch=0 if observed_at is not None else None,
        eligible_high_pivot=None,
        eligible_low_pivot=None,
    )


def _context(
    index: int,
    *,
    high: str | int,
    low: str | int,
    close: str | int,
    ema20: str | int | None,
    trend: NStructureKind,
) -> JdjBarContext:
    return _context_at(
        _START + timedelta(minutes=index),
        high=high,
        low=low,
        close=close,
        ema20=ema20,
        trend=trend,
    )


def _undefined(index: int) -> JdjBarContext:
    return _context(
        index,
        high=101,
        low=99,
        close=100,
        ema20=100,
        trend=NStructureKind.UNDEFINED,
    )


def _high_pivot(confirmed_at: datetime) -> NSwingPivot:
    pivot_time = confirmed_at - timedelta(minutes=5)
    return NSwingPivot(
        pivot_id=":".join(
            (
                _CONTRACT,
                _SEGMENT_START.isoformat(),
                "5m",
                "0",
                "high",
                pivot_time.isoformat(),
            )
        ),
        epoch=0,
        kind=NSwingPivotKind.HIGH,
        source_timeframe=BarFrequency.M5,
        pivot_time=pivot_time,
        confirmed_at=confirmed_at,
        price=Decimal("105"),
        contract=_CONTRACT,
        segment_start_trading_day=_SEGMENT_START,
    )


def _reduce(
    contexts: tuple[JdjBarContext, ...],
    **changes: object,
) -> JdjTrendFollowTrace:
    arguments: dict[str, object] = {
        "symbol": _SYMBOL,
        "contract": _CONTRACT,
        "segment_start_trading_day": _SEGMENT_START,
    }
    arguments.update(changes)
    return reduce_jdj_trend_follow(
        contexts,
        **arguments,  # type: ignore[arg-type]
    )


def _assert_context_error(call) -> JdjContextError:  # type: ignore[no-untyped-def]
    with pytest.raises(JdjContextError) as captured:
        call()
    error = captured.value
    assert error.code == "JDJ_CONTEXT_INVALID"
    assert str(error) == "JDJ_CONTEXT_INVALID"
    assert error.__cause__ is None
    return error


@pytest.mark.parametrize(
    ("direction", "trend", "reaction", "trigger"),
    (
        (
            JdjDirection.LONG,
            NStructureKind.BULL,
            {"high": 105, "low": 95, "close": 101, "ema20": 100},
            {"high": 106, "low": 101, "close": 102, "ema20": 100},
        ),
        (
            JdjDirection.SHORT,
            NStructureKind.BEAR,
            {"high": 105, "low": 95, "close": 99, "ema20": 100},
            {"high": 98, "low": 94, "close": 97, "ema20": 100},
        ),
    ),
)
def test_exact_ema_reaction_arms_then_later_bar_triggers(
    direction: JdjDirection,
    trend: NStructureKind,
    reaction: dict[str, int],
    trigger: dict[str, int],
) -> None:
    contexts = (
        _undefined(0),
        _context(1, trend=trend, **reaction),
        _context(2, trend=trend, **trigger),
    )

    trace = _reduce(contexts)

    assert trace.ambiguous_count == 0
    assert trace.invalidated_count == 0
    assert len(trace.events) == 1
    event = trace.events[0]
    assert event.direction is direction
    assert event.reaction_at == contexts[1].bar.bar_end
    assert event.observed_at == contexts[2].bar.bar_end
    assert event.ema20_at_reaction == Decimal("100")
    assert event.trigger_level == (
        contexts[1].bar.high
        if direction is JdjDirection.LONG
        else contexts[1].bar.low
    )
    assert event.observation_close == contexts[2].bar.close


@pytest.mark.parametrize(
    ("trend", "reaction_close"),
    (
        (NStructureKind.BULL, 100),
        (NStructureKind.BEAR, 100),
        (NStructureKind.RANGE, 101),
        (NStructureKind.UNDEFINED, 101),
    ),
)
def test_touch_without_close_on_trend_side_or_direction_has_no_setup(
    trend: NStructureKind,
    reaction_close: int,
) -> None:
    contexts = (
        _undefined(0),
        _context(
            1,
            high=105,
            low=95,
            close=reaction_close,
            ema20=100,
            trend=trend,
        ),
        _context(
            2,
            high=110,
            low=90,
            close=reaction_close,
            ema20=100,
            trend=trend,
        ),
    )

    assert _reduce(contexts) == JdjTrendFollowTrace(
        events=(),
        ambiguous_count=0,
        invalidated_count=0,
    )


@pytest.mark.parametrize(
    ("trend", "non_touch", "later_extreme"),
    (
        (
            NStructureKind.BULL,
            {"high": 105, "low": 101, "close": 102, "ema20": 100},
            {"high": 106, "low": 102, "close": 103, "ema20": 100},
        ),
        (
            NStructureKind.BEAR,
            {"high": 99, "low": 95, "close": 98, "ema20": 100},
            {"high": 98, "low": 94, "close": 97, "ema20": 100},
        ),
    ),
)
def test_close_on_trend_side_without_ema_touch_does_not_arm(
    trend: NStructureKind,
    non_touch: dict[str, int],
    later_extreme: dict[str, int],
) -> None:
    contexts = (
        _undefined(0),
        _context(1, trend=trend, **non_touch),
        _context(2, trend=trend, **later_extreme),
    )

    assert _reduce(contexts).events == ()


def test_reaction_boundary_cannot_also_trigger() -> None:
    contexts = (
        _undefined(0),
        _context(
            1,
            high=110,
            low=99,
            close=101,
            ema20=100,
            trend=NStructureKind.BULL,
        ),
    )

    trace = _reduce(contexts)

    assert trace.events == ()
    assert trace.ambiguous_count == 0
    assert trace.invalidated_count == 0


def test_dynamic_trigger_uses_latest_previous_bar_not_reaction_bar() -> None:
    contexts = (
        _undefined(0),
        _context(
            1,
            high=110,
            low=99,
            close=101,
            ema20=100,
            trend=NStructureKind.BULL,
        ),
        _context(
            2,
            high=105,
            low=101,
            close=102,
            ema20=100,
            trend=NStructureKind.BULL,
        ),
        _context(
            3,
            high=106,
            low=102,
            close=103,
            ema20=100,
            trend=NStructureKind.BULL,
        ),
    )

    event = _reduce(contexts).events[0]

    assert event.observed_at == contexts[3].bar.bar_end
    assert event.trigger_level == Decimal("105")
    assert contexts[3].bar.high < contexts[1].bar.high


@pytest.mark.parametrize(
    ("trend", "reaction", "equal_bar", "strict_bar", "expected_level"),
    (
        (
            NStructureKind.BULL,
            {"high": 105, "low": 95, "close": 101, "ema20": 100},
            {"high": 105, "low": 101, "close": 102, "ema20": 100},
            {"high": 106, "low": 102, "close": 103, "ema20": 100},
            Decimal("105"),
        ),
        (
            NStructureKind.BEAR,
            {"high": 105, "low": 95, "close": 99, "ema20": 100},
            {"high": 99, "low": 95, "close": 98, "ema20": 100},
            {"high": 98, "low": 94, "close": 97, "ema20": 100},
            Decimal("95"),
        ),
    ),
)
def test_equal_previous_bar_extreme_does_not_trigger(
    trend: NStructureKind,
    reaction: dict[str, int],
    equal_bar: dict[str, int],
    strict_bar: dict[str, int],
    expected_level: Decimal,
) -> None:
    prefix = (
        _undefined(0),
        _context(1, trend=trend, **reaction),
        _context(2, trend=trend, **equal_bar),
    )
    contexts = (*prefix, _context(3, trend=trend, **strict_bar))

    assert _reduce(prefix).events == ()
    event = _reduce(contexts).events[0]
    assert event.observed_at == contexts[3].bar.bar_end
    assert event.trigger_level == expected_level


@pytest.mark.parametrize(
    ("armed_trend", "lost_trend", "reaction"),
    (
        (
            NStructureKind.BULL,
            NStructureKind.RANGE,
            {"high": 105, "low": 95, "close": 101, "ema20": 100},
        ),
        (
            NStructureKind.BEAR,
            NStructureKind.UNDEFINED,
            {"high": 105, "low": 95, "close": 99, "ema20": 100},
        ),
    ),
)
def test_preknown_trend_loss_invalidates_before_price_trigger(
    armed_trend: NStructureKind,
    lost_trend: NStructureKind,
    reaction: dict[str, int],
) -> None:
    contexts = (
        _undefined(0),
        _context(1, trend=armed_trend, **reaction),
        _context(
            2,
            high=110,
            low=90,
            close=100,
            ema20=100,
            trend=lost_trend,
        ),
    )

    trace = _reduce(contexts)

    assert trace.events == ()
    assert trace.ambiguous_count == 0
    assert trace.invalidated_count == 1


@pytest.mark.parametrize(
    ("trend", "reaction_close", "invalidating_close"),
    (
        (NStructureKind.BULL, 101, 100),
        (NStructureKind.BEAR, 99, 100),
    ),
)
def test_equal_ema_close_invalidates_armed_episode(
    trend: NStructureKind,
    reaction_close: int,
    invalidating_close: int,
) -> None:
    contexts = (
        _undefined(0),
        _context(
            1,
            high=105,
            low=95,
            close=reaction_close,
            ema20=100,
            trend=trend,
        ),
        _context(
            2,
            high=104,
            low=96,
            close=invalidating_close,
            ema20=100,
            trend=trend,
        ),
    )

    trace = _reduce(contexts)

    assert trace.events == ()
    assert trace.ambiguous_count == 0
    assert trace.invalidated_count == 1


@pytest.mark.parametrize(
    ("trend", "reaction", "ambiguous"),
    (
        (
            NStructureKind.BULL,
            {"high": 105, "low": 95, "close": 101, "ema20": 100},
            {"high": 106, "low": 94, "close": 100, "ema20": 100},
        ),
        (
            NStructureKind.BEAR,
            {"high": 105, "low": 95, "close": 99, "ema20": 100},
            {"high": 106, "low": 94, "close": 100, "ema20": 100},
        ),
    ),
)
def test_price_trigger_plus_ema_invalidation_is_ambiguous_no_event(
    trend: NStructureKind,
    reaction: dict[str, int],
    ambiguous: dict[str, int],
) -> None:
    contexts = (
        _undefined(0),
        _context(1, trend=trend, **reaction),
        _context(2, trend=trend, **ambiguous),
    )

    trace = _reduce(contexts)

    assert trace.events == ()
    assert trace.ambiguous_count == 1
    assert trace.invalidated_count == 0


def test_day_change_terminates_old_episode_and_skips_reset_boundary() -> None:
    day_one = (
        _undefined(0),
        _context(
            1,
            high=105,
            low=95,
            close=101,
            ema20=100,
            trend=NStructureKind.BULL,
        ),
    )
    day_two_start = datetime(2026, 8, 20, 1, 1, tzinfo=UTC)
    day_two = (
        _context_at(
            day_two_start,
            high=106,
            low=95,
            close=100,
            ema20=100,
            trend=NStructureKind.UNDEFINED,
            trading_day=_NEXT_TRADING_DAY,
        ),
        _context_at(
            day_two_start + timedelta(minutes=1),
            high=107,
            low=99,
            close=101,
            ema20=100,
            trend=NStructureKind.BULL,
            trading_day=_NEXT_TRADING_DAY,
        ),
        _context_at(
            day_two_start + timedelta(minutes=2),
            high=108,
            low=101,
            close=102,
            ema20=100,
            trend=NStructureKind.BULL,
            trading_day=_NEXT_TRADING_DAY,
        ),
    )

    trace = _reduce((*day_one, *day_two))

    assert len(trace.events) == 1
    assert trace.events[0].reaction_at == day_two[1].bar.bar_end
    assert trace.events[0].observed_at == day_two[2].bar.bar_end


def test_session_gap_rejects_fact_newer_than_previous_1m_boundary() -> None:
    previous_end = datetime(2026, 8, 19, 1, 0, tzinfo=UTC)
    reaction_end = datetime(2026, 8, 19, 1, 10, tzinfo=UTC)
    future_snapshot = previous_end + timedelta(minutes=5)
    contexts = (
        _context_at(
            previous_end,
            high=101,
            low=99,
            close=100,
            ema20=100,
            trend=NStructureKind.UNDEFINED,
        ),
        _context_at(
            reaction_end,
            high=105,
            low=95,
            close=101,
            ema20=100,
            trend=NStructureKind.BULL,
            snapshot_at=future_snapshot,
        ),
    )

    _assert_context_error(lambda: _reduce(contexts))


def test_session_gap_rejects_pivot_newer_than_previous_1m_boundary() -> None:
    previous_end = datetime(2026, 8, 19, 1, 0, tzinfo=UTC)
    reaction_end = datetime(2026, 8, 19, 1, 10, tzinfo=UTC)
    context = _context_at(
        reaction_end,
        high=105,
        low=95,
        close=101,
        ema20=100,
        trend=NStructureKind.BULL,
        snapshot_at=previous_end,
    )
    context = replace(
        context,
        eligible_high_pivot=_high_pivot(
            previous_end + timedelta(minutes=5)
        ),
    )
    contexts = (
        _context_at(
            previous_end,
            high=101,
            low=99,
            close=100,
            ema20=100,
            trend=NStructureKind.UNDEFINED,
        ),
        context,
    )

    _assert_context_error(lambda: _reduce(contexts))


def test_fact_at_previous_1m_boundary_is_eligible_after_session_gap() -> None:
    previous_end = datetime(2026, 8, 19, 1, 0, tzinfo=UTC)
    reaction_end = datetime(2026, 8, 19, 1, 10, tzinfo=UTC)
    reaction = _context_at(
        reaction_end,
        high=105,
        low=95,
        close=101,
        ema20=100,
        trend=NStructureKind.BULL,
        snapshot_at=previous_end,
    )
    reaction = replace(
        reaction,
        eligible_high_pivot=_high_pivot(previous_end),
    )
    contexts = (
        _context_at(
            previous_end,
            high=101,
            low=99,
            close=100,
            ema20=100,
            trend=NStructureKind.UNDEFINED,
        ),
        reaction,
        _context_at(
            reaction_end + timedelta(minutes=1),
            high=106,
            low=101,
            close=102,
            ema20=100,
            trend=NStructureKind.BULL,
            snapshot_at=previous_end,
        ),
    )

    event = _reduce(contexts).events[0]

    assert event.reaction_at == reaction_end
    assert event.observed_at == reaction_end + timedelta(minutes=1)


def test_terminal_episode_can_be_followed_by_new_later_reaction_same_day() -> None:
    contexts = (
        _undefined(0),
        _context(1, high=105, low=95, close=101, ema20=100, trend=NStructureKind.BULL),
        _context(2, high=106, low=101, close=102, ema20=100, trend=NStructureKind.BULL),
        _context(3, high=105, low=95, close=101, ema20=100, trend=NStructureKind.BULL),
        _context(4, high=106, low=101, close=102, ema20=100, trend=NStructureKind.BULL),
    )

    trace = _reduce(contexts)

    assert tuple(event.reaction_at for event in trace.events) == (
        contexts[1].bar.bar_end,
        contexts[3].bar.bar_end,
    )
    assert tuple(event.observed_at for event in trace.events) == (
        contexts[2].bar.bar_end,
        contexts[4].bar.bar_end,
    )


def test_event_identity_provenance_and_value_object_are_exact() -> None:
    contexts = (
        _undefined(0),
        _context(1, high=105, low=95, close=101, ema20=100, trend=NStructureKind.BULL),
        _context(2, high=106, low=101, close=102, ema20=100, trend=NStructureKind.BULL),
    )

    event = _reduce(contexts).events[0]

    assert tuple(field.name for field in fields(event)) == (
        "event_id",
        "source_kind",
        "setup_kind",
        "candidate_id",
        "source_event_kind",
        "direction",
        "symbol",
        "contract",
        "segment_start_trading_day",
        "trading_day",
        "observed_at",
        "segment_bar_index",
        "trend_snapshot_observed_at",
        "reaction_at",
        "ema20_at_reaction",
        "trigger_level",
        "observation_close",
    )
    assert event.event_id == (
        "jdj_trend_follow_1m_candidate_v1|jm|JM2701|2026-08-03|long|"
        "2026-08-19T01:02:00+00:00|2026-08-19T01:03:00+00:00|105"
    )
    assert event.source_kind == "jdj_1m"
    assert event.setup_kind is JdjSetupKind.TREND_FOLLOW
    assert event.candidate_id == "jdj_trend_follow_1m_candidate_v1"
    assert event.source_event_kind == "jdj_trend_follow_triggered"
    assert event.symbol == _SYMBOL
    assert event.contract == _CONTRACT
    assert event.segment_start_trading_day == _SEGMENT_START
    assert event.trading_day == _TRADING_DAY
    assert event.segment_bar_index == 2
    assert event.trend_snapshot_observed_at == contexts[1].trend_snapshot_observed_at
    assert isinstance(event, JdjTrendFollowTriggerEvent)
    with pytest.raises(FrozenInstanceError):
        event.event_id = "changed"  # type: ignore[misc]
    _assert_context_error(lambda: replace(event, event_id="changed"))


def test_same_exact_input_has_stable_event_id_and_prefix_is_causal() -> None:
    prefix = (
        _undefined(0),
        _context(1, high=105, low=95, close=101, ema20=100, trend=NStructureKind.BULL),
        _context(2, high=106, low=101, close=102, ema20=100, trend=NStructureKind.BULL),
    )
    suffix = (
        _context(3, high=105, low=95, close=101, ema20=100, trend=NStructureKind.BULL),
        _context(4, high=106, low=101, close=102, ema20=100, trend=NStructureKind.BULL),
    )

    first = _reduce(prefix)
    repeated = _reduce(prefix)
    full = _reduce((*prefix, *suffix))

    assert first == repeated
    assert full.events[: len(first.events)] == first.events
    assert tuple(
        (event.observed_at, event.segment_bar_index, event.event_id)
        for event in full.events
    ) == tuple(
        sorted(
            (
                event.observed_at,
                event.segment_bar_index,
                event.event_id,
            )
            for event in full.events
        )
    )


def test_missing_ema_after_arming_is_impossible_context() -> None:
    contexts = (
        _undefined(0),
        _context(1, high=105, low=95, close=101, ema20=100, trend=NStructureKind.BULL),
        _context(2, high=106, low=101, close=102, ema20=None, trend=NStructureKind.BULL),
    )

    _assert_context_error(lambda: _reduce(contexts))


@pytest.mark.parametrize(
    "call",
    (
        lambda: _reduce((), symbol="JM"),
        lambda: _reduce((), contract="jm2701"),
        lambda: _reduce((), contract="RB2710"),
        lambda: _reduce((), segment_start_trading_day=datetime(2026, 8, 3)),
        lambda: _reduce((_undefined(1), _undefined(0))),
        lambda: _reduce(
            (
                _context_at(
                    _START,
                    high=101,
                    low=99,
                    close=100,
                    ema20=100,
                    trend=NStructureKind.UNDEFINED,
                    trading_day=date(2026, 8, 2),
                ),
            )
        ),
        lambda: _reduce(
            (
                replace(
                    _context(
                        0,
                        high=101,
                        low=99,
                        close=100,
                        ema20=100,
                        trend=NStructureKind.BULL,
                    ),
                    trend_snapshot_observed_at=None,
                    trend_epoch=None,
                ),
            )
        ),
        lambda: _reduce(
            (
                _context_at(
                    _START,
                    high=101,
                    low=99,
                    close=100,
                    ema20=100,
                    trend=NStructureKind.BULL,
                    snapshot_at=_START,
                ),
            )
        ),
    ),
)
def test_invalid_identity_series_or_context_fails_closed(call) -> None:  # type: ignore[no-untyped-def]
    _assert_context_error(call)


def test_public_enums_and_trace_are_frozen_and_exact() -> None:
    assert tuple(JdjDirection) == (JdjDirection.LONG, JdjDirection.SHORT)
    assert tuple(item.value for item in JdjDirection) == ("long", "short")
    assert tuple(JdjSetupKind) == (
        JdjSetupKind.TREND_FOLLOW,
        JdjSetupKind.TREND_REENTRY_6,
        JdjSetupKind.KEY_LEVEL_BREAKOUT,
    )
    assert tuple(item.value for item in JdjSetupKind) == (
        "trend_follow",
        "trend_reentry_6",
        "key_level_breakout",
    )
    trace = JdjTrendFollowTrace(
        events=(),
        ambiguous_count=0,
        invalidated_count=0,
    )
    with pytest.raises(FrozenInstanceError):
        trace.invalidated_count = 1  # type: ignore[misc]
    _assert_context_error(lambda: replace(trace, ambiguous_count=-1))
