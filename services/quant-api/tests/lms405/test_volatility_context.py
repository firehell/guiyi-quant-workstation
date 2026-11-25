from datetime import datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from lms405_volatility_context import before_shape_checks, minute_context, prior_atr, prior_days


T0 = datetime.fromisoformat("2026-10-22T21:00:00+08:00")
US = timedelta(microseconds=1)


def bar(end, op, hi, lo, close):
    return SimpleNamespace(
        bar_end=end, trading_day=end.date(),
        open=Decimal(op), high=Decimal(hi), low=Decimal(lo), close=Decimal(close),
    )


def test_atr_only_uses_completed_prior_dailies_and_first_close_anchor():
    dailies = [bar(T0 - timedelta(days=15), 89, 105, 88, 89)]
    dailies += [bar(T0 - timedelta(days=days), 100, 105, 95, 100) for days in range(14, 0, -1)]
    dates = [item.trading_day for item in dailies]
    total, ranges = prior_atr(dailies, expected=dates, before=T0)
    assert total == 16 + 13 * 10
    assert ranges == ["16"] + ["10"] * 13
    with pytest.raises(ValueError, match="ATR_DAILY_PREFIX_UNVERIFIED"):
        prior_atr(dailies, expected=dates, before=dailies[-1].bar_end + US)
    with pytest.raises(ValueError, match="ATR_DAILY_PREFIX_UNVERIFIED"):
        prior_atr(dailies[1:], expected=dates, before=T0)


def test_missing_calendar_day_between_prior_close_and_night_is_rejected():
    day = T0.date()
    calendar = [(day - timedelta(days=offset), offset != 1) for offset in range(16, -1, -1)]
    assert prior_days(calendar, day)[-1] == day - timedelta(days=2)
    with pytest.raises(ValueError, match="TRADING_CALENDAR_PREFIX_GAP"):
        prior_days(calendar[:-2] + calendar[-1:], day)


def test_range_gap_and_true_range_are_distinct_and_use_strict_availability():
    n = bar(T0 + timedelta(minutes=1), 105, 106, 105, 106)
    d = bar(T0 + timedelta(hours=12, minutes=1), 99, 100, 99, 100)
    args = dict(initial_close=Decimal(100), atr_total=Decimal(5 * 14), day_reopen_end=d.bar_end)
    assert not minute_context([n, d], as_of=n.bar_end + US, **args)
    prefix = minute_context([n, d], as_of=n.bar_end + 2 * US, **args)
    (night,) = prefix
    assert night["exceeds_atr14"] == {
        "trading_day_range": False, "trading_day_true_range": True,
        "opening_gap_abs": False, "day_reopen_gap_abs": None,
    }
    full = minute_context([n, d], as_of=d.bar_end + 2 * US, **args)
    assert full[:1] == prefix
    assert full[-1]["day_reopen_gap_signed"] == -7
    assert full[-1]["exceeds_atr14"]["day_reopen_gap_abs"]


def test_period_context_cannot_use_atr_cross_observed_after_shape_started():
    early, crossing = (
        bar(T0 + timedelta(minutes=offset), 100, high, 100, high)
        for offset, high in ((1, 101), (2, 108))
    )
    rows = minute_context(
        [early, crossing], initial_close=Decimal(100), atr_total=Decimal(5 * 14),
        day_reopen_end=None, as_of=crossing.bar_end + 2 * US,
    )
    after_shape = dict(shape_end=(T0 + timedelta(minutes=3)).isoformat(),
                       confirmed_at=(T0 + timedelta(minutes=4)).isoformat())
    (point,) = before_shape_checks(
        {"hypotheses": {"1m_to_1m": {"events": [after_shape]}}}, rows,
    )["1m_to_1m"]
    assert point["shape_start"] == crossing.bar_end
    assert point["context_bar_end"] == early.bar_end
    assert not point["known_before_shape"]["trading_day_range"]
