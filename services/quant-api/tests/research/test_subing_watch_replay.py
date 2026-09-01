from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from app.market_data.domain import CanonicalBar
from app.market_data.subing_watch.contracts import (
    SubingWatchSourceIdentity,
    load_subing_watch_policy,
)
from app.market_data.subing_watch.replay import (
    SubingWatchReplayError,
    replay_subing_watch_segment,
)


DAY = date(2026, 9, 1)
START = datetime(2026, 9, 1, tzinfo=UTC)


def _bar(index: int, *, close: str = "100", minutes: int = 15) -> CanonicalBar:
    value = Decimal(close)
    return CanonicalBar(
        bar_end=START + timedelta(minutes=minutes * index),
        trading_day=DAY,
        open=value,
        high=value,
        low=value,
        close=value,
        volume=Decimal(100 + index),
        turnover=None,
        open_interest=None,
    )


def _identity(contract: str = "JM2601", start: date = DAY) -> SubingWatchSourceIdentity:
    return SubingWatchSourceIdentity("jm", contract, start)


def test_replay_steps_each_completed_bar_once_and_freezes_coverage() -> None:
    bars = tuple(_bar(index) for index in range(1, 5))

    projected = replay_subing_watch_segment(
        _identity(),
        bars,
        (),
        load_subing_watch_policy(),
    )

    assert projected.identity == _identity()
    assert projected.coverage == (bars[0].bar_end, bars[-1].bar_end)
    assert tuple(item.bar_end for item in projected.evaluations) == tuple(
        bar.bar_end for bar in bars
    )
    assert projected.final_state.last_evaluation is not None
    assert projected.final_state.last_evaluation.bar_end == bars[-1].bar_end.isoformat()


def test_each_physical_segment_starts_with_fresh_warmup_state() -> None:
    first_bars = tuple(_bar(index) for index in range(1, 35))
    second_day = DAY + timedelta(days=1)
    second_bar = replace(
        _bar(35, close="140"),
        trading_day=second_day,
        bar_end=START + timedelta(days=1, minutes=15),
    )

    first = replay_subing_watch_segment(
        _identity(), first_bars, (), load_subing_watch_policy()
    )
    second = replay_subing_watch_segment(
        _identity("JM2605", second_day),
        (second_bar,),
        (),
        load_subing_watch_policy(),
    )

    assert first.final_state.sma21_window
    assert second.final_state.sma21_window == (140.0,)
    assert second.evaluations[0].ma21 is None
    assert second.evaluations[0].observation_types == ()


def test_future_60m_bar_is_unavailable_and_never_gates_15m_evaluation() -> None:
    bars = tuple(_bar(index) for index in range(1, 36))
    future_60m = replace(
        _bar(10, minutes=60),
        bar_end=bars[-1].bar_end + timedelta(hours=1),
    )

    projected = replay_subing_watch_segment(
        _identity(), bars, (future_60m,), load_subing_watch_policy()
    )

    assert projected.evaluations[-1].outcome in {
        "evaluated_no_signal",
        "evaluated_candidate",
    }
    assert projected.evaluations[-1].context.higher_timeframe_alignment == "unavailable"


def test_latest_completed_same_segment_60m_context_is_used_at_cutoff() -> None:
    bars_15m = tuple(_bar(index) for index in range(1, 121))
    bars_60m = tuple(_bar(index, minutes=60) for index in range(1, 26))

    projected = replay_subing_watch_segment(
        _identity(), bars_15m, bars_60m, load_subing_watch_policy()
    )

    assert projected.evaluations[-1].context.higher_timeframe_alignment == "neutral"
    assert projected.latest_higher_timeframe is not None
    assert projected.latest_higher_timeframe.bar_end == bars_60m[-1].bar_end.isoformat()


def test_exact_duplicate_is_a_deterministic_noop() -> None:
    bar = _bar(1)

    projected = replay_subing_watch_segment(
        _identity(), (bar, bar), (), load_subing_watch_policy()
    )

    assert len(projected.evaluations) == 1
    assert projected.evaluations[0].bar_end == bar.bar_end
    assert projected.evaluations[0].outcome == "source_unavailable"
    assert projected.evaluations[0].public_reason_codes == (
        "SOURCE_WINDOW_UNAVAILABLE",
    )
    assert projected.final_state.sma21_window == (100.0,)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("turnover", Decimal("1000")),
        ("open_interest", Decimal("20")),
        ("trading_day", DAY + timedelta(days=1)),
    ],
)
def test_same_bar_end_with_any_canonical_field_conflict_fails_closed(
    field: str,
    value: object,
) -> None:
    bar = _bar(1)
    conflict = replace(bar, **{field: value})

    with pytest.raises(SubingWatchReplayError, match="SUBING_WATCH_REPLAY_INVALID"):
        replay_subing_watch_segment(
            _identity(), (bar, conflict), (), load_subing_watch_policy()
        )


def test_replay_rejects_empty_or_out_of_segment_coverage() -> None:
    policy = load_subing_watch_policy()
    with pytest.raises(SubingWatchReplayError, match="SUBING_WATCH_REPLAY_INVALID"):
        replay_subing_watch_segment(_identity(), (), (), policy)

    before_segment = replace(_bar(1), trading_day=DAY - timedelta(days=1))
    with pytest.raises(SubingWatchReplayError, match="SUBING_WATCH_REPLAY_INVALID"):
        replay_subing_watch_segment(_identity(), (before_segment,), (), policy)


def test_replay_rejects_trading_day_regression_even_when_bar_end_increases() -> None:
    day_two = DAY + timedelta(days=1)
    bars = (
        _bar(1),
        replace(
            _bar(2),
            bar_end=START + timedelta(days=1, minutes=15),
            trading_day=day_two,
        ),
        replace(
            _bar(3),
            bar_end=START + timedelta(days=1, minutes=30),
            trading_day=DAY,
        ),
    )

    with pytest.raises(SubingWatchReplayError, match="SUBING_WATCH_REPLAY_INVALID"):
        replay_subing_watch_segment(_identity(), bars, (), load_subing_watch_policy())
