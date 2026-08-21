from __future__ import annotations

from dataclasses import FrozenInstanceError, fields, replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import TypedDict

import pytest

from app.market_data.domain import BarFrequency, CanonicalBar
from app.research.jdj.jdj_context import JdjBarContext, JdjContextError
from app.research.jdj.jdj_events import (
    JdjDirection,
    JdjKeyLevelBreakoutTriggerEvent,
    JdjSetupKind,
)
from app.research.jdj.jdj_key_level_breakout import (
    JdjKeyLevelBreakoutTrace,
    reduce_jdj_key_level_breakout,
)
from app.research.n_structure.n_structure_state import NStructureKind
from app.research.n_structure.n_structure_swing import NSwingPivot, NSwingPivotKind


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


def _pivot(
    kind: NSwingPivotKind,
    *,
    price: str | int = 100,
    epoch: int = 0,
    pivot_time: datetime | None = None,
    confirmed_at: datetime | None = None,
    contract: str = _CONTRACT,
    segment_start: date = _SEGMENT_START,
) -> NSwingPivot:
    pivot_at = pivot_time or _START - timedelta(minutes=5)
    confirmed = confirmed_at or _START
    pivot_id = ":".join(
        (
            contract,
            segment_start.isoformat(),
            "5m",
            str(epoch),
            kind.value,
            pivot_at.isoformat(),
        )
    )
    return NSwingPivot(
        pivot_id=pivot_id,
        epoch=epoch,
        kind=kind,
        source_timeframe=BarFrequency.M5,
        pivot_time=pivot_at,
        confirmed_at=confirmed,
        price=Decimal(str(price)),
        contract=contract,
        segment_start_trading_day=segment_start,
    )


_HIGH_PIVOT = _pivot(NSwingPivotKind.HIGH)
_LOW_PIVOT = _pivot(NSwingPivotKind.LOW)
_NEWER_HIGH_PIVOT = _pivot(
    NSwingPivotKind.HIGH,
    price=105,
    pivot_time=_START - timedelta(minutes=4),
)


def _context_at(
    bar_end: datetime,
    *,
    high: str | int,
    low: str | int,
    close: str | int,
    trend: NStructureKind,
    pivot: NSwingPivot | None = None,
    epoch: int = 0,
    snapshot_at: datetime | None = None,
    ema20: str | int | None = 100,
    trading_day: date = _TRADING_DAY,
) -> JdjBarContext:
    close_value = Decimal(str(close))
    has_snapshot = trend is not NStructureKind.UNDEFINED
    observed_at = (
        snapshot_at
        if snapshot_at is not None
        else bar_end - timedelta(minutes=1)
    ) if has_snapshot else None
    return JdjBarContext(
        bar=CanonicalBar(
            bar_end=bar_end,
            trading_day=trading_day,
            open=close_value,
            high=Decimal(str(high)),
            low=Decimal(str(low)),
            close=close_value,
            volume=Decimal("100"),
            turnover=None,
            open_interest=None,
        ),
        ema20=Decimal(str(ema20)) if ema20 is not None else None,
        trend_kind=trend,
        trend_snapshot_observed_at=observed_at,
        trend_epoch=epoch if has_snapshot else None,
        eligible_high_pivot=(
            pivot if pivot is not None and pivot.kind is NSwingPivotKind.HIGH
            else None
        ),
        eligible_low_pivot=(
            pivot if pivot is not None and pivot.kind is NSwingPivotKind.LOW
            else None
        ),
    )


def _context(
    index: int,
    *,
    high: str | int,
    low: str | int,
    close: str | int,
    trend: NStructureKind,
    pivot: NSwingPivot | None = None,
    epoch: int = 0,
    ema20: str | int | None = 100,
) -> JdjBarContext:
    return _context_at(
        _START + timedelta(minutes=index),
        high=high,
        low=low,
        close=close,
        trend=trend,
        pivot=pivot,
        epoch=epoch,
        ema20=ema20,
    )


def _undefined(index: int, *, ema20: str | int | None = 100) -> JdjBarContext:
    return _context(
        index,
        high=101,
        low=99,
        close=100,
        trend=NStructureKind.UNDEFINED,
        ema20=ema20,
    )


def _long_success(
    *,
    pivot: NSwingPivot = _HIGH_PIVOT,
    ema_values: tuple[str | int | None, ...] = (100, 100, 100, 100, 100),
) -> tuple[JdjBarContext, ...]:
    return (
        _undefined(0, ema20=ema_values[0]),
        _context(
            1,
            high=101,
            low=98,
            close=99,
            trend=NStructureKind.BULL,
            pivot=pivot,
            ema20=ema_values[1],
        ),
        _context(
            2,
            high=103,
            low=99,
            close=101,
            trend=NStructureKind.BULL,
            pivot=pivot,
            ema20=ema_values[2],
        ),
        _context(
            3,
            high=102,
            low=100,
            close=101,
            trend=NStructureKind.BULL,
            pivot=pivot,
            ema20=ema_values[3],
        ),
        _context(
            4,
            high=103,
            low=101,
            close=102,
            trend=NStructureKind.BULL,
            pivot=pivot,
            ema20=ema_values[4],
        ),
    )


def _short_success(
    *,
    pivot: NSwingPivot = _LOW_PIVOT,
) -> tuple[JdjBarContext, ...]:
    return (
        _undefined(0),
        _context(
            1,
            high=102,
            low=99,
            close=101,
            trend=NStructureKind.BEAR,
            pivot=pivot,
        ),
        _context(
            2,
            high=101,
            low=97,
            close=99,
            trend=NStructureKind.BEAR,
            pivot=pivot,
        ),
        _context(
            3,
            high=100,
            low=98,
            close=99,
            trend=NStructureKind.BEAR,
            pivot=pivot,
        ),
        _context(
            4,
            high=99,
            low=97,
            close=98,
            trend=NStructureKind.BEAR,
            pivot=pivot,
        ),
    )


def _reduce(
    contexts: tuple[JdjBarContext, ...] | list[JdjBarContext],
    **changes: object,
) -> JdjKeyLevelBreakoutTrace:
    arguments: dict[str, object] = {
        "symbol": _SYMBOL,
        "contract": _CONTRACT,
        "segment_start_trading_day": _SEGMENT_START,
    }
    arguments.update(changes)
    return reduce_jdj_key_level_breakout(
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


def _terminal_pivot(trend: NStructureKind) -> NSwingPivot | None:
    if trend is NStructureKind.BEAR:
        return _LOW_PIVOT
    if trend is NStructureKind.UNDEFINED:
        return None
    return _HIGH_PIVOT


@pytest.mark.parametrize(
    ("contexts", "direction", "pivot", "trigger_level"),
    (
        (
            _long_success(),
            JdjDirection.LONG,
            _HIGH_PIVOT,
            Decimal("102"),
        ),
        (
            _short_success(),
            JdjDirection.SHORT,
            _LOW_PIVOT,
            Decimal("98"),
        ),
    ),
)
def test_exact_second_chance_sequence_emits_immutable_provenance(
    contexts: tuple[JdjBarContext, ...],
    direction: JdjDirection,
    pivot: NSwingPivot,
    trigger_level: Decimal,
) -> None:
    trace = _reduce(contexts)

    assert trace.ambiguous_count == 0
    assert trace.invalidated_count == 0
    assert trace.expired_no_retest_count == 0
    assert trace.expired_context_lost_count == 0
    assert len(trace.events) == 1
    event = trace.events[0]
    assert event.direction is direction
    assert event.trend_epoch == pivot.epoch
    assert event.key_level_pivot_id == pivot.pivot_id
    assert event.key_level_price == pivot.price
    assert event.key_level_confirmed_at == pivot.confirmed_at
    assert event.first_break_at == contexts[2].bar.bar_end
    assert event.retest_at == contexts[3].bar.bar_end
    assert event.observed_at == contexts[4].bar.bar_end
    assert event.trigger_level == trigger_level
    assert event.observation_close == contexts[4].bar.close
    assert event.trend_snapshot_observed_at == (
        contexts[3].trend_snapshot_observed_at
    )


@pytest.mark.parametrize(
    ("trend", "wrong_pivot"),
    (
        (NStructureKind.BULL, _LOW_PIVOT),
        (NStructureKind.BEAR, _HIGH_PIVOT),
    ),
)
def test_wrong_pivot_kind_cannot_start_episode(
    trend: NStructureKind,
    wrong_pivot: NSwingPivot,
) -> None:
    contexts = (
        _undefined(0),
        _context(1, high=102, low=98, close=100, trend=trend, pivot=wrong_pivot),
        _context(2, high=103, low=97, close=101, trend=trend, pivot=wrong_pivot),
        _context(3, high=104, low=98, close=102, trend=trend, pivot=wrong_pivot),
    )

    assert _reduce(contexts).events == ()


@pytest.mark.parametrize(
    ("trend", "pivot", "bars"),
    (
        (
            NStructureKind.BULL,
            _HIGH_PIVOT,
            (
                (103, 100, 101),
                (102, 100, 101),
                (103, 101, 102),
                (101, 98, 99),
                (103, 99, 101),
                (102, 100, 101),
                (103, 101, 102),
            ),
        ),
        (
            NStructureKind.BEAR,
            _LOW_PIVOT,
            (
                (100, 97, 99),
                (100, 98, 99),
                (99, 97, 98),
                (102, 99, 101),
                (101, 97, 99),
                (100, 98, 99),
                (99, 97, 98),
            ),
        ),
    ),
)
def test_price_already_beyond_level_cannot_infer_origin_side(
    trend: NStructureKind,
    pivot: NSwingPivot,
    bars: tuple[tuple[int, int, int], ...],
) -> None:
    contexts = (
        _undefined(0),
        *tuple(
            _context(
                index + 1,
                high=high,
                low=low,
                close=close,
                trend=trend,
                pivot=pivot,
            )
            for index, (high, low, close) in enumerate(bars)
        ),
    )

    assert _reduce(contexts[:4]).events == ()
    event = _reduce(contexts).events[0]
    assert event.first_break_at == contexts[5].bar.bar_end


def test_new_pivot_before_first_break_requires_its_own_origin_observation() -> None:
    newer = _pivot(
        NSwingPivotKind.HIGH,
        price=105,
        pivot_time=_START - timedelta(minutes=4),
        confirmed_at=_START + timedelta(minutes=1),
    )
    contexts = (
        _undefined(0),
        _context(1, high=101, low=98, close=99, trend=NStructureKind.BULL, pivot=_HIGH_PIVOT),
        _context(2, high=107, low=104, close=106, trend=NStructureKind.BULL, pivot=newer),
        _context(3, high=106, low=105, close=106, trend=NStructureKind.BULL, pivot=newer),
        _context(4, high=106, low=103, close=104, trend=NStructureKind.BULL, pivot=newer),
        _context(5, high=107, low=104, close=106, trend=NStructureKind.BULL, pivot=newer),
        _context(6, high=106, low=105, close=106, trend=NStructureKind.BULL, pivot=newer),
        _context(7, high=107, low=106, close=107, trend=NStructureKind.BULL, pivot=newer),
    )

    assert _reduce(contexts[:4]).events == ()
    event = _reduce(contexts).events[0]
    assert event.key_level_pivot_id == newer.pivot_id
    assert event.first_break_at == contexts[5].bar.bar_end


@pytest.mark.parametrize(
    ("trend", "pivot", "bars", "expected_first_break"),
    (
        (
            NStructureKind.BULL,
            _HIGH_PIVOT,
            ((101, 98, 99), (103, 99, 100), (103, 100, 101), (102, 100, 101), (103, 101, 102)),
            3,
        ),
        (
            NStructureKind.BEAR,
            _LOW_PIVOT,
            ((102, 99, 101), (101, 97, 100), (100, 97, 99), (100, 98, 99), (99, 97, 98)),
            3,
        ),
    ),
)
def test_first_break_requires_close_transition_and_cannot_retest_same_bar(
    trend: NStructureKind,
    pivot: NSwingPivot,
    bars: tuple[tuple[int, int, int], ...],
    expected_first_break: int,
) -> None:
    contexts = (
        _undefined(0),
        *tuple(
            _context(
                index + 1,
                high=high,
                low=low,
                close=close,
                trend=trend,
                pivot=pivot,
            )
            for index, (high, low, close) in enumerate(bars)
        ),
    )

    assert _reduce(contexts[: expected_first_break + 1]).events == ()
    event = _reduce(contexts).events[0]
    assert event.first_break_at == contexts[expected_first_break].bar.bar_end
    assert event.retest_at == contexts[expected_first_break + 1].bar.bar_end


def test_first_break_freezes_pivot_and_ignores_newer_same_epoch_pivot() -> None:
    newer = _pivot(
        NSwingPivotKind.HIGH,
        price=105,
        pivot_time=_START - timedelta(minutes=4),
        confirmed_at=_START + timedelta(minutes=2),
    )
    contexts = (
        *_long_success()[:3],
        _context(3, high=102, low=100, close=101, trend=NStructureKind.BULL, pivot=newer),
        _context(4, high=103, low=101, close=102, trend=NStructureKind.BULL, pivot=newer),
    )

    event = _reduce(contexts).events[0]

    assert event.key_level_pivot_id == _HIGH_PIVOT.pivot_id
    assert event.key_level_price == Decimal("100")


@pytest.mark.parametrize(
    ("trend", "pivot", "failed", "later"),
    (
        (
            NStructureKind.BULL,
            _HIGH_PIVOT,
            (101, 98, 99),
            ((102, 100, 101), (103, 101, 102)),
        ),
        (
            NStructureKind.BEAR,
            _LOW_PIVOT,
            (102, 99, 101),
            ((100, 98, 99), (99, 97, 98)),
        ),
    ),
)
def test_failed_retest_is_terminal_and_consumes_same_pivot(
    trend: NStructureKind,
    pivot: NSwingPivot,
    failed: tuple[int, int, int],
    later: tuple[tuple[int, int, int], ...],
) -> None:
    success_prefix = _long_success()[:3] if trend is NStructureKind.BULL else _short_success()[:3]
    contexts = (
        *success_prefix,
        _context(3, high=failed[0], low=failed[1], close=failed[2], trend=trend, pivot=pivot),
        *tuple(
            _context(
                index + 4,
                high=values[0],
                low=values[1],
                close=values[2],
                trend=trend,
                pivot=pivot,
            )
            for index, values in enumerate(later)
        ),
    )

    trace = _reduce(contexts)

    assert trace.events == ()
    assert trace.ambiguous_count == 0
    assert trace.invalidated_count == 0


@pytest.mark.parametrize(
    ("contexts", "terminal", "ambiguous", "invalidated"),
    (
        (
            _long_success()[:-1],
            {"high": 103, "low": 98, "close": 100, "trend": NStructureKind.BULL},
            1,
            0,
        ),
        (
            _short_success()[:-1],
            {"high": 102, "low": 97, "close": 100, "trend": NStructureKind.BEAR},
            1,
            0,
        ),
        (
            _long_success()[:-1],
            {"high": 102, "low": 98, "close": 100, "trend": NStructureKind.BULL},
            0,
            1,
        ),
        (
            _short_success()[:-1],
            {"high": 102, "low": 98, "close": 100, "trend": NStructureKind.BEAR},
            0,
            1,
        ),
        (
            _long_success()[:-1],
            {"high": 110, "low": 90, "close": 101, "trend": NStructureKind.RANGE},
            0,
            1,
        ),
        (
            _short_success()[:-1],
            {"high": 110, "low": 90, "close": 99, "trend": NStructureKind.UNDEFINED},
            0,
            1,
        ),
    ),
)
def test_armed_terminal_semantics_use_frozen_level_not_ema(
    contexts: tuple[JdjBarContext, ...],
    terminal: _TerminalBar,
    ambiguous: int,
    invalidated: int,
) -> None:
    full = (
        *contexts,
        _context(
            4,
            pivot=_terminal_pivot(terminal["trend"]),
            ema20=999,
            **terminal,
        ),
    )

    trace = _reduce(full)

    assert trace.events == ()
    assert trace.ambiguous_count == ambiguous
    assert trace.invalidated_count == invalidated


def test_ema_readiness_or_value_changes_do_not_affect_key_level_setup() -> None:
    contexts = _long_success(ema_values=(None, 999, None, 1, None))

    event = _reduce(contexts).events[0]

    assert event.key_level_price == Decimal("100")
    assert event.observed_at == contexts[-1].bar.bar_end


def test_waiting_retest_expires_only_when_next_day_proves_day_end() -> None:
    waiting = _long_success()[:3]
    next_start = datetime(2026, 8, 20, 1, 1, tzinfo=UTC)
    next_boundary = _context_at(
        next_start,
        high=101,
        low=99,
        close=100,
        trend=NStructureKind.UNDEFINED,
        ema20=None,
        trading_day=_NEXT_TRADING_DAY,
    )

    prefix = _reduce(waiting)
    after_boundary = _reduce((*waiting, next_boundary))

    assert prefix.expired_no_retest_count == 0
    assert after_boundary.expired_no_retest_count == 1
    assert after_boundary.expired_context_lost_count == 0


def test_waiting_retest_trend_or_epoch_loss_expires_context() -> None:
    newer_epoch = _pivot(
        NSwingPivotKind.HIGH,
        epoch=1,
        pivot_time=_START - timedelta(minutes=4),
        confirmed_at=_START + timedelta(minutes=2),
    )
    contexts = (
        *_long_success()[:3],
        _context(
            3,
            high=102,
            low=100,
            close=101,
            trend=NStructureKind.BULL,
            pivot=newer_epoch,
            epoch=1,
        ),
        _context(
            4,
            high=102,
            low=100,
            close=101,
            trend=NStructureKind.BULL,
            pivot=newer_epoch,
            epoch=1,
        ),
        _context(
            5,
            high=103,
            low=101,
            close=102,
            trend=NStructureKind.BULL,
            pivot=newer_epoch,
            epoch=1,
        ),
    )

    trace = _reduce(contexts)

    assert trace.events == ()
    assert trace.expired_context_lost_count == 1


def test_same_pivot_cannot_create_second_episode_but_new_pivot_can() -> None:
    first = _long_success()
    same_pivot_retry = (
        _context(5, high=101, low=98, close=99, trend=NStructureKind.BULL, pivot=_HIGH_PIVOT),
        _context(6, high=103, low=99, close=101, trend=NStructureKind.BULL, pivot=_HIGH_PIVOT),
        _context(7, high=102, low=100, close=101, trend=NStructureKind.BULL, pivot=_HIGH_PIVOT),
        _context(8, high=103, low=101, close=102, trend=NStructureKind.BULL, pivot=_HIGH_PIVOT),
    )
    newer = _pivot(
        NSwingPivotKind.HIGH,
        price=105,
        pivot_time=_START - timedelta(minutes=4),
        confirmed_at=_START + timedelta(minutes=8),
    )
    new_pivot_episode = (
        _context(9, high=106, low=103, close=104, trend=NStructureKind.BULL, pivot=newer),
        _context(10, high=107, low=104, close=106, trend=NStructureKind.BULL, pivot=newer),
        _context(11, high=106, low=105, close=106, trend=NStructureKind.BULL, pivot=newer),
        _context(12, high=107, low=106, close=107, trend=NStructureKind.BULL, pivot=newer),
    )

    trace = _reduce((*first, *same_pivot_retry, *new_pivot_episode))

    assert len(trace.events) == 2
    assert trace.events[0].key_level_pivot_id == _HIGH_PIVOT.pivot_id
    assert trace.events[1].key_level_pivot_id == newer.pivot_id


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
        "trend_epoch",
        "key_level_pivot_id",
        "key_level_price",
        "key_level_confirmed_at",
        "first_break_at",
        "retest_at",
        "trigger_level",
        "observation_close",
    )
    assert event.event_id == (
        "jdj_key_level_breakout_1m_candidate_v1|jm|JM2701|2026-08-03|"
        "long|0|JM2701:2026-08-03:5m:0:high:2026-08-19T00:56:00+00:00|"
        "100|2026-08-19T01:01:00+00:00|2026-08-19T01:03:00+00:00|"
        "2026-08-19T01:04:00+00:00|2026-08-19T01:05:00+00:00|102"
    )
    assert event.source_kind == "jdj_1m"
    assert event.setup_kind is JdjSetupKind.KEY_LEVEL_BREAKOUT
    assert event.candidate_id == "jdj_key_level_breakout_1m_candidate_v1"
    assert event.source_event_kind == "jdj_key_level_breakout_triggered"
    assert isinstance(event, JdjKeyLevelBreakoutTriggerEvent)
    assert tuple(field.name for field in fields(trace)) == (
        "events",
        "ambiguous_count",
        "invalidated_count",
        "expired_no_retest_count",
        "expired_context_lost_count",
    )
    assert not hasattr(event, "ema20")
    assert not hasattr(event, "fill_price")
    assert not hasattr(event, "position")
    assert not hasattr(event, "pnl")
    with pytest.raises(FrozenInstanceError):
        event.event_id = "changed"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        trace.invalidated_count = 1  # type: ignore[misc]
    _assert_context_error(lambda: replace(event, event_id="changed"))
    _assert_context_error(lambda: replace(trace, expired_no_retest_count=-1))


@pytest.mark.parametrize(
    "invalid_pivot_id",
    (
        "JM2701:2026-08-03:5m:0:low:2026-08-19T00:56:00+00:00",
        "JM2701:2026-08-03:5m:1:high:2026-08-19T00:56:00+00:00",
        "RB2710:2026-08-03:5m:0:high:2026-08-19T00:56:00+00:00",
        "not-a-pivot",
    ),
)
def test_event_rejects_structurally_mismatched_pivot_identity(
    invalid_pivot_id: str,
) -> None:
    event = _reduce(_long_success()).events[0]
    changed_event_id = event.event_id.replace(
        event.key_level_pivot_id,
        invalid_pivot_id,
    )

    _assert_context_error(
        lambda: replace(
            event,
            event_id=changed_event_id,
            key_level_pivot_id=invalid_pivot_id,
        )
    )


def test_same_input_is_stable_and_future_suffix_does_not_change_prefix() -> None:
    prefix = _long_success()
    newer = _pivot(
        NSwingPivotKind.HIGH,
        price=105,
        pivot_time=_START - timedelta(minutes=4),
        confirmed_at=_START + timedelta(minutes=4),
    )
    suffix = (
        _context(5, high=106, low=103, close=104, trend=NStructureKind.BULL, pivot=newer),
        _context(6, high=107, low=104, close=106, trend=NStructureKind.BULL, pivot=newer),
        _context(7, high=106, low=105, close=106, trend=NStructureKind.BULL, pivot=newer),
        _context(8, high=107, low=106, close=107, trend=NStructureKind.BULL, pivot=newer),
    )

    first = _reduce(list(prefix))
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


def test_session_gap_future_snapshot_or_pivot_fails_strict_before() -> None:
    previous_end = datetime(2026, 8, 19, 1, 0, tzinfo=UTC)
    current_end = datetime(2026, 8, 19, 1, 10, tzinfo=UTC)
    future_pivot = _pivot(
        NSwingPivotKind.HIGH,
        pivot_time=previous_end - timedelta(minutes=5),
        confirmed_at=previous_end + timedelta(minutes=5),
    )
    first = _context_at(
        previous_end,
        high=101,
        low=99,
        close=100,
        trend=NStructureKind.UNDEFINED,
    )
    future_snapshot = _context_at(
        current_end,
        high=103,
        low=101,
        close=102,
        trend=NStructureKind.BULL,
        snapshot_at=previous_end + timedelta(minutes=5),
    )
    future_pivot_context = _context_at(
        current_end,
        high=103,
        low=101,
        close=102,
        trend=NStructureKind.BULL,
        pivot=future_pivot,
        snapshot_at=previous_end,
    )

    _assert_context_error(lambda: _reduce((first, future_snapshot)))
    _assert_context_error(lambda: _reduce((first, future_pivot_context)))


@pytest.mark.parametrize(
    "contexts",
    (
        (
            _undefined(0),
            _context(
                1,
                high=106,
                low=103,
                close=104,
                trend=NStructureKind.BULL,
                pivot=_NEWER_HIGH_PIVOT,
            ),
            _context(
                2,
                high=101,
                low=98,
                close=99,
                trend=NStructureKind.BULL,
                pivot=_HIGH_PIVOT,
            ),
        ),
        (
            _undefined(0),
            _context(
                1,
                high=106,
                low=103,
                close=104,
                trend=NStructureKind.BULL,
                pivot=_NEWER_HIGH_PIVOT,
            ),
            _context(
                2,
                high=106,
                low=103,
                close=104,
                trend=NStructureKind.BULL,
            ),
            _context(
                3,
                high=106,
                low=103,
                close=104,
                trend=NStructureKind.BULL,
                pivot=_NEWER_HIGH_PIVOT,
            ),
        ),
    ),
)
def test_same_epoch_pivot_projection_cannot_regress_or_reappear(
    contexts: tuple[JdjBarContext, ...],
) -> None:
    _assert_context_error(lambda: _reduce(contexts))


def test_segment_epoch_cannot_regress_across_trading_day_reset() -> None:
    epoch_one = _pivot(NSwingPivotKind.HIGH, epoch=1)
    next_start = datetime(2026, 8, 20, 1, 1, tzinfo=UTC)
    next_epoch_zero = _pivot(
        NSwingPivotKind.HIGH,
        pivot_time=next_start - timedelta(minutes=5),
        confirmed_at=next_start,
    )
    contexts = (
        _undefined(0),
        _context(
            1,
            high=101,
            low=98,
            close=99,
            trend=NStructureKind.BULL,
            pivot=epoch_one,
            epoch=1,
        ),
        _context_at(
            next_start,
            high=101,
            low=99,
            close=100,
            trend=NStructureKind.UNDEFINED,
            trading_day=_NEXT_TRADING_DAY,
        ),
        _context_at(
            next_start + timedelta(minutes=1),
            high=101,
            low=98,
            close=99,
            trend=NStructureKind.BULL,
            pivot=next_epoch_zero,
            epoch=0,
            trading_day=_NEXT_TRADING_DAY,
        ),
    )

    _assert_context_error(lambda: _reduce(contexts))


@pytest.mark.parametrize(
    "drifted_pivot",
    (
        _pivot(NSwingPivotKind.HIGH, price=105),
        _pivot(
            NSwingPivotKind.HIGH,
            confirmed_at=_START + timedelta(minutes=1),
        ),
    ),
)
def test_same_pivot_id_cannot_drift_immutable_facts(
    drifted_pivot: NSwingPivot,
) -> None:
    contexts = (
        _undefined(0),
        _context(
            1,
            high=101,
            low=98,
            close=99,
            trend=NStructureKind.BULL,
            pivot=_HIGH_PIVOT,
        ),
        _context(
            2,
            high=106,
            low=103,
            close=104,
            trend=NStructureKind.BULL,
            pivot=drifted_pivot,
        ),
    )

    assert drifted_pivot.pivot_id == _HIGH_PIVOT.pivot_id
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
                _context(
                    0,
                    high=101,
                    low=99,
                    close=100,
                    trend=NStructureKind.BULL,
                ),
            )
        ),
        lambda: _reduce(
            (
                _undefined(0),
                _context(
                    1,
                    high=101,
                    low=98,
                    close=99,
                    trend=NStructureKind.BULL,
                    pivot=_pivot(
                        NSwingPivotKind.HIGH,
                        contract="RB2710",
                    ),
                ),
            )
        ),
        lambda: _reduce(
            (
                _undefined(0),
                _context(
                    1,
                    high=101,
                    low=98,
                    close=99,
                    trend=NStructureKind.BULL,
                    pivot=_pivot(NSwingPivotKind.HIGH, epoch=1),
                    epoch=1,
                ),
                _context(
                    2,
                    high=101,
                    low=98,
                    close=99,
                    trend=NStructureKind.BULL,
                    pivot=_HIGH_PIVOT,
                    epoch=0,
                ),
            )
        ),
        lambda: _reduce(
            (
                _undefined(0),
                _context(
                    1,
                    high=101,
                    low=98,
                    close=99,
                    trend=NStructureKind.BULL,
                    pivot=_pivot(NSwingPivotKind.HIGH, epoch=1),
                    epoch=1,
                ),
                _undefined(2),
                _context(
                    3,
                    high=101,
                    low=98,
                    close=99,
                    trend=NStructureKind.BULL,
                    pivot=_HIGH_PIVOT,
                    epoch=0,
                ),
            )
        ),
    ),
)
def test_invalid_identity_series_or_context_fails_closed(call) -> None:  # type: ignore[no-untyped-def]
    _assert_context_error(call)
