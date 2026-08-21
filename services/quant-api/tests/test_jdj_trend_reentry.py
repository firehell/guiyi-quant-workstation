from __future__ import annotations

from dataclasses import FrozenInstanceError, fields, replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import TypedDict

import pytest

from app.market_data.domain import CanonicalBar
from app.research.jdj.jdj_context import JdjBarContext, JdjContextError
from app.research.jdj.jdj_trend_reentry import (
    JdjTrendReentryTrace,
    reduce_jdj_trend_reentry_6,
)
from app.research.jdj.jdj_events import (
    JdjDirection,
    JdjSetupKind,
    JdjTrendReentryTriggerEvent,
)
from app.research.n_structure.n_structure_state import NStructureKind


_SYMBOL = "jm"
_CONTRACT = "JM2701"
_SEGMENT_START = date(2026, 8, 3)
_TRADING_DAY = date(2026, 8, 19)
_NEXT_TRADING_DAY = date(2026, 8, 20)
_START = datetime(2026, 8, 19, 1, 1, tzinfo=UTC)


class _TerminalBar(TypedDict):
    high: int
    low: int
    close: int
    trend: NStructureKind


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
    high_value = Decimal(str(high))
    low_value = Decimal(str(low))
    close_value = Decimal(str(close))
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
        ema20=Decimal(str(ema20)) if ema20 is not None else None,
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
    ema20: str | int | None = 100,
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
        trend=NStructureKind.UNDEFINED,
    )


def _long_success() -> tuple[JdjBarContext, ...]:
    return (
        _undefined(0),
        _context(1, high=103, low=101, close=102, trend=NStructureKind.BULL),
        _context(2, high=101, low=95, close=99, trend=NStructureKind.BULL),
        _context(3, high=100, low=94, close=98, trend=NStructureKind.BULL),
        _context(4, high=103, low=93, close=101, trend=NStructureKind.BULL),
        _context(5, high=103, low=99, close=101, trend=NStructureKind.BULL),
        _context(6, high=104, low=101, close=102, trend=NStructureKind.BULL),
    )


def _short_success() -> tuple[JdjBarContext, ...]:
    return (
        _undefined(0),
        _context(1, high=99, low=97, close=98, trend=NStructureKind.BEAR),
        _context(2, high=105, low=99, close=101, trend=NStructureKind.BEAR),
        _context(3, high=106, low=100, close=102, trend=NStructureKind.BEAR),
        _context(4, high=107, low=97, close=99, trend=NStructureKind.BEAR),
        _context(5, high=101, low=97, close=99, trend=NStructureKind.BEAR),
        _context(6, high=98, low=96, close=97, trend=NStructureKind.BEAR),
    )


def _reduce(
    contexts: tuple[JdjBarContext, ...],
    **changes: object,
) -> JdjTrendReentryTrace:
    arguments: dict[str, object] = {
        "symbol": _SYMBOL,
        "contract": _CONTRACT,
        "segment_start_trading_day": _SEGMENT_START,
    }
    arguments.update(changes)
    return reduce_jdj_trend_reentry_6(
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
    ("contexts", "direction", "extreme", "trigger_level"),
    (
        (
            _long_success(),
            JdjDirection.LONG,
            Decimal("94"),
            Decimal("103"),
        ),
        (
            _short_success(),
            JdjDirection.SHORT,
            Decimal("106"),
            Decimal("97"),
        ),
    ),
)
def test_exact_reentry_sequence_emits_immutable_provenance(
    contexts: tuple[JdjBarContext, ...],
    direction: JdjDirection,
    extreme: Decimal,
    trigger_level: Decimal,
) -> None:
    trace = _reduce(contexts)

    assert trace.ambiguous_count == 0
    assert trace.invalidated_count == 0
    assert len(trace.events) == 1
    event = trace.events[0]
    assert event.direction is direction
    assert event.excursion_started_at == contexts[2].bar.bar_end
    assert event.excursion_extreme == extreme
    assert event.reclaimed_at == contexts[4].bar.bar_end
    assert event.reaction_at == contexts[5].bar.bar_end
    assert event.observed_at == contexts[6].bar.bar_end
    assert event.trigger_level == trigger_level
    assert event.observation_close == contexts[6].bar.close
    assert event.trend_snapshot_observed_at == (
        contexts[5].trend_snapshot_observed_at
    )


@pytest.mark.parametrize(
    ("trend", "initial_opposite", "later_sequence", "excursion_index"),
    (
        (
            NStructureKind.BULL,
            {"high": 101, "low": 95, "close": 99},
            (
                {"high": 103, "low": 99, "close": 101},
                {"high": 104, "low": 99, "close": 101},
                {"high": 105, "low": 101, "close": 102},
                {"high": 101, "low": 94, "close": 99},
                {"high": 103, "low": 98, "close": 101},
                {"high": 103, "low": 99, "close": 101},
                {"high": 104, "low": 101, "close": 102},
            ),
            5,
        ),
        (
            NStructureKind.BEAR,
            {"high": 105, "low": 99, "close": 101},
            (
                {"high": 101, "low": 97, "close": 99},
                {"high": 101, "low": 96, "close": 99},
                {"high": 99, "low": 95, "close": 98},
                {"high": 106, "low": 99, "close": 101},
                {"high": 102, "low": 97, "close": 99},
                {"high": 101, "low": 97, "close": 99},
                {"high": 98, "low": 96, "close": 97},
            ),
            5,
        ),
    ),
)
def test_starting_opposite_ema_side_cannot_infer_prior_prerequisite(
    trend: NStructureKind,
    initial_opposite: dict[str, int],
    later_sequence: tuple[dict[str, int], ...],
    excursion_index: int,
) -> None:
    early = (
        _undefined(0),
        _context(1, trend=trend, **initial_opposite),
        *tuple(
            _context(index + 2, trend=trend, **values)
            for index, values in enumerate(later_sequence[:3])
        ),
    )
    contexts = (
        *early,
        *tuple(
            _context(index + 5, trend=trend, **values)
            for index, values in enumerate(later_sequence[3:])
        ),
    )

    assert _reduce(early).events == ()
    event = _reduce(contexts).events[0]
    assert event.excursion_started_at == contexts[excursion_index].bar.bar_end


@pytest.mark.parametrize(
    ("trend", "sequence", "expected_reaction_index"),
    (
        (
            NStructureKind.BULL,
            (
                {"high": 103, "low": 101, "close": 102},
                {"high": 101, "low": 95, "close": 99},
                {"high": 103, "low": 96, "close": 101},
                {"high": 104, "low": 102, "close": 103},
                {"high": 103, "low": 99, "close": 101},
                {"high": 104, "low": 101, "close": 102},
            ),
            5,
        ),
        (
            NStructureKind.BEAR,
            (
                {"high": 99, "low": 97, "close": 98},
                {"high": 105, "low": 99, "close": 101},
                {"high": 104, "low": 97, "close": 99},
                {"high": 98, "low": 96, "close": 97},
                {"high": 101, "low": 97, "close": 99},
                {"high": 98, "low": 96, "close": 97},
            ),
            5,
        ),
    ),
)
def test_reclaim_bar_cannot_be_reaction(
    trend: NStructureKind,
    sequence: tuple[dict[str, int], ...],
    expected_reaction_index: int,
) -> None:
    contexts = (
        _undefined(0),
        *tuple(
            _context(index + 1, trend=trend, **values)
            for index, values in enumerate(sequence)
        ),
    )

    assert _reduce(contexts[:5]).events == ()
    event = _reduce(contexts).events[0]
    assert event.reaction_at == contexts[expected_reaction_index].bar.bar_end


@pytest.mark.parametrize(
    ("trend", "sequence"),
    (
        (
            NStructureKind.BULL,
            (
                {"high": 103, "low": 101, "close": 102},
                {"high": 101, "low": 95, "close": 99},
                {"high": 103, "low": 96, "close": 101},
                {"high": 103, "low": 94, "close": 101},
                {"high": 103, "low": 99, "close": 101},
                {"high": 104, "low": 101, "close": 102},
            ),
        ),
        (
            NStructureKind.BEAR,
            (
                {"high": 99, "low": 97, "close": 98},
                {"high": 105, "low": 99, "close": 101},
                {"high": 104, "low": 97, "close": 99},
                {"high": 106, "low": 97, "close": 99},
                {"high": 101, "low": 97, "close": 99},
                {"high": 98, "low": 96, "close": 97},
            ),
        ),
    ),
)
def test_first_failed_post_reclaim_reaction_is_terminal(
    trend: NStructureKind,
    sequence: tuple[dict[str, int], ...],
) -> None:
    contexts = (
        _undefined(0),
        *tuple(
            _context(index + 1, trend=trend, **values)
            for index, values in enumerate(sequence)
        ),
    )

    trace = _reduce(contexts)

    assert trace.events == ()
    assert trace.ambiguous_count == 0
    assert trace.invalidated_count == 0


@pytest.mark.parametrize(
    ("trend", "sequence", "expected_start", "expected_extreme"),
    (
        (
            NStructureKind.BULL,
            (
                {"high": 103, "low": 101, "close": 102},
                {"high": 101, "low": 95, "close": 99},
                {"high": 103, "low": 96, "close": 101},
                {"high": 101, "low": 93, "close": 99},
                {"high": 100, "low": 92, "close": 98},
                {"high": 103, "low": 94, "close": 101},
                {"high": 103, "low": 96, "close": 101},
                {"high": 104, "low": 101, "close": 102},
            ),
            4,
            Decimal("92"),
        ),
        (
            NStructureKind.BEAR,
            (
                {"high": 99, "low": 97, "close": 98},
                {"high": 105, "low": 99, "close": 101},
                {"high": 104, "low": 97, "close": 99},
                {"high": 107, "low": 99, "close": 101},
                {"high": 108, "low": 100, "close": 102},
                {"high": 106, "low": 97, "close": 99},
                {"high": 104, "low": 97, "close": 99},
                {"high": 98, "low": 96, "close": 97},
            ),
            4,
            Decimal("108"),
        ),
    ),
)
def test_reclaim_failure_starts_independent_excursion_at_current_bar(
    trend: NStructureKind,
    sequence: tuple[dict[str, int], ...],
    expected_start: int,
    expected_extreme: Decimal,
) -> None:
    contexts = (
        _undefined(0),
        *tuple(
            _context(index + 1, trend=trend, **values)
            for index, values in enumerate(sequence)
        ),
    )

    event = _reduce(contexts).events[0]

    assert event.excursion_started_at == contexts[expected_start].bar.bar_end
    assert event.excursion_extreme == expected_extreme


def test_dynamic_trigger_references_latest_previous_bar() -> None:
    contexts = (
        *_long_success()[:-2],
        _context(5, high=110, low=99, close=101, trend=NStructureKind.BULL),
        _context(6, high=105, low=101, close=102, trend=NStructureKind.BULL),
        _context(7, high=106, low=102, close=103, trend=NStructureKind.BULL),
    )

    event = _reduce(contexts).events[0]

    assert event.observed_at == contexts[7].bar.bar_end
    assert event.trigger_level == Decimal("105")
    assert contexts[7].bar.high < contexts[5].bar.high


@pytest.mark.parametrize(
    ("contexts", "equal_bar", "strict_bar", "expected_level"),
    (
        (
            _long_success()[:-1],
            {"high": 103, "low": 101, "close": 102},
            {"high": 104, "low": 102, "close": 103},
            Decimal("103"),
        ),
        (
            _short_success()[:-1],
            {"high": 98, "low": 97, "close": 98},
            {"high": 97, "low": 96, "close": 97},
            Decimal("97"),
        ),
    ),
)
def test_equal_previous_extreme_does_not_trigger(
    contexts: tuple[JdjBarContext, ...],
    equal_bar: dict[str, int],
    strict_bar: dict[str, int],
    expected_level: Decimal,
) -> None:
    trend = contexts[-1].trend_kind
    prefix = (*contexts, _context(6, trend=trend, **equal_bar))
    full = (*prefix, _context(7, trend=trend, **strict_bar))

    assert _reduce(prefix).events == ()
    assert _reduce(full).events[0].trigger_level == expected_level


@pytest.mark.parametrize(
    ("contexts", "terminal", "ambiguous", "invalidated"),
    (
        (
            _long_success()[:-1],
            {"high": 104, "low": 94, "close": 100, "trend": NStructureKind.BULL},
            1,
            0,
        ),
        (
            _short_success()[:-1],
            {"high": 106, "low": 96, "close": 100, "trend": NStructureKind.BEAR},
            1,
            0,
        ),
        (
            _long_success()[:-1],
            {"high": 102, "low": 94, "close": 100, "trend": NStructureKind.BULL},
            0,
            1,
        ),
        (
            _short_success()[:-1],
            {"high": 106, "low": 98, "close": 100, "trend": NStructureKind.BEAR},
            0,
            1,
        ),
        (
            _long_success()[:-1],
            {"high": 110, "low": 90, "close": 100, "trend": NStructureKind.RANGE},
            0,
            1,
        ),
        (
            _short_success()[:-1],
            {"high": 110, "low": 90, "close": 100, "trend": NStructureKind.UNDEFINED},
            0,
            1,
        ),
    ),
)
def test_armed_terminal_semantics_are_exact(
    contexts: tuple[JdjBarContext, ...],
    terminal: _TerminalBar,
    ambiguous: int,
    invalidated: int,
) -> None:
    full = (*contexts, _context(6, ema20=100, **terminal))

    trace = _reduce(full)

    assert trace.events == ()
    assert trace.ambiguous_count == ambiguous
    assert trace.invalidated_count == invalidated


def test_day_reset_discards_armed_state_and_requires_new_sequence() -> None:
    armed_day_one = _long_success()[:-1]
    next_start = datetime(2026, 8, 20, 1, 1, tzinfo=UTC)
    day_two = (
        _context_at(
            next_start,
            high=104,
            low=101,
            close=102,
            ema20=100,
            trend=NStructureKind.UNDEFINED,
            trading_day=_NEXT_TRADING_DAY,
        ),
        _context_at(
            next_start + timedelta(minutes=1),
            high=103,
            low=101,
            close=102,
            ema20=100,
            trend=NStructureKind.BULL,
            trading_day=_NEXT_TRADING_DAY,
        ),
        _context_at(
            next_start + timedelta(minutes=2),
            high=101,
            low=95,
            close=99,
            ema20=100,
            trend=NStructureKind.BULL,
            trading_day=_NEXT_TRADING_DAY,
        ),
        _context_at(
            next_start + timedelta(minutes=3),
            high=103,
            low=96,
            close=101,
            ema20=100,
            trend=NStructureKind.BULL,
            trading_day=_NEXT_TRADING_DAY,
        ),
        _context_at(
            next_start + timedelta(minutes=4),
            high=103,
            low=97,
            close=101,
            ema20=100,
            trend=NStructureKind.BULL,
            trading_day=_NEXT_TRADING_DAY,
        ),
        _context_at(
            next_start + timedelta(minutes=5),
            high=104,
            low=101,
            close=102,
            ema20=100,
            trend=NStructureKind.BULL,
            trading_day=_NEXT_TRADING_DAY,
        ),
    )

    trace = _reduce((*armed_day_one, *day_two))

    assert len(trace.events) == 1
    assert trace.events[0].trading_day == _NEXT_TRADING_DAY
    assert trace.events[0].excursion_started_at == day_two[2].bar.bar_end


def test_event_contract_id_and_trace_fields_are_exact_and_frozen() -> None:
    contexts = _long_success()

    trace = _reduce(contexts)
    event = trace.events[0]

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
        "excursion_started_at",
        "excursion_extreme",
        "reclaimed_at",
        "reaction_at",
        "trigger_level",
        "observation_close",
    )
    assert event.event_id == (
        "jdj_trend_reentry_6_1m_candidate_v1|jm|JM2701|2026-08-03|long|"
        "2026-08-19T01:03:00+00:00|94|2026-08-19T01:05:00+00:00|"
        "2026-08-19T01:06:00+00:00|2026-08-19T01:07:00+00:00|103"
    )
    assert event.source_kind == "jdj_1m"
    assert event.setup_kind is JdjSetupKind.TREND_REENTRY_6
    assert event.candidate_id == "jdj_trend_reentry_6_1m_candidate_v1"
    assert event.source_event_kind == "jdj_trend_reentry_6_triggered"
    assert isinstance(event, JdjTrendReentryTriggerEvent)
    assert tuple(field.name for field in fields(trace)) == (
        "events",
        "ambiguous_count",
        "invalidated_count",
    )
    assert not hasattr(event, "fill_price")
    assert not hasattr(event, "position")
    assert not hasattr(event, "pnl")
    with pytest.raises(FrozenInstanceError):
        event.event_id = "changed"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        trace.invalidated_count = 1  # type: ignore[misc]
    _assert_context_error(lambda: replace(event, event_id="changed"))
    _assert_context_error(lambda: replace(trace, ambiguous_count=-1))


def test_same_input_is_stable_and_future_suffix_does_not_change_prefix() -> None:
    prefix = _long_success()
    suffix = (
        _context(7, high=103, low=101, close=102, trend=NStructureKind.BULL),
        _context(8, high=101, low=95, close=99, trend=NStructureKind.BULL),
        _context(9, high=103, low=96, close=101, trend=NStructureKind.BULL),
        _context(10, high=103, low=97, close=101, trend=NStructureKind.BULL),
        _context(11, high=104, low=101, close=102, trend=NStructureKind.BULL),
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


def test_session_gap_future_snapshot_fails_strict_before() -> None:
    previous_end = datetime(2026, 8, 19, 1, 0, tzinfo=UTC)
    current_end = datetime(2026, 8, 19, 1, 10, tzinfo=UTC)
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
            current_end,
            high=103,
            low=101,
            close=102,
            ema20=100,
            trend=NStructureKind.BULL,
            snapshot_at=previous_end + timedelta(minutes=5),
        ),
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
                replace(
                    _context(
                        0,
                        high=101,
                        low=99,
                        close=100,
                        trend=NStructureKind.BULL,
                    ),
                    trend_snapshot_observed_at=None,
                    trend_epoch=None,
                ),
            )
        ),
        lambda: _reduce(
            (
                _undefined(0),
                _context(
                    1,
                    high=103,
                    low=101,
                    close=102,
                    trend=NStructureKind.BULL,
                ),
                _context(
                    2,
                    high=101,
                    low=95,
                    close=99,
                    ema20=None,
                    trend=NStructureKind.BULL,
                ),
            )
        ),
    ),
)
def test_invalid_identity_series_or_context_fails_closed(call) -> None:  # type: ignore[no-untyped-def]
    _assert_context_error(call)
