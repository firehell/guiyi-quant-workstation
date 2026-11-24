from datetime import date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from guiyi_quant.lms405 import Bar
import lms405_structure_crosscheck as study_module
from lms405_structure_crosscheck import compare_frozen_july, match


def test_earlier_anchor_does_not_expand_candidate_window_or_include_cutoff():
    start = datetime.fromisoformat("2025-07-22T09:00:00+08:00")
    end = start + timedelta(minutes=5)
    values = tuple(map(Decimal, (100, 102, 99, 101)))
    prior = Bar("JM2509", start - timedelta(hours=1), *values, start=start - timedelta(minutes=65))
    current = Bar("JM2509", end, *values, start=start)
    minutes = [SimpleNamespace(bar_end=b.end, low=b.low, high=b.high, close=b.close) for b in (prior, current)]
    just_before = match((minutes, [prior, current]), start, end, ("102",))
    assert just_before["window_fives"] == 0
    assert just_before["anchor_matches"]["102"]["minutes"]["high"] == [prior.end.isoformat()]
    after = match((minutes, [prior, current]), start, end + timedelta(microseconds=2), ("102",))
    assert after["window_fives"] == 1 and after["prior_observed_close"] == Decimal(101)
    assert after["anchor_matches"]["102"]["minutes"]["high"] == [prior.end.isoformat(), end.isoformat()]


def test_existing_july_fixture_quality_does_not_allow_ohlc_drift():
    end = datetime.fromisoformat("2025-07-22T09:05:00+08:00")
    frozen = [dict(bar_end_utc=end.isoformat(), open="100", high="102", low="99", close="101")]
    original = SimpleNamespace(trading_day=date(2025, 7, 22), bar_end=end,
                               open=Decimal(100), high=Decimal(102), low=Decimal(99), close=Decimal(101))
    source_days = (date(2025, 7, 22),)
    compare_frozen_july([original], frozen=frozen, days=source_days)
    with pytest.raises(ValueError, match="JULY_FROZEN_OHLC_DIVERGED"):
        compare_frozen_july([], frozen=frozen, days=source_days)
    original.close = Decimal(100)
    with pytest.raises(ValueError, match="JULY_FROZEN_OHLC_DIVERGED"):
        compare_frozen_july([original], frozen=frozen, days=source_days)


def test_authoritative_open_after_cutoff_does_not_require_future_partition(monkeypatch):
    case = next(row for row in study_module.WINDOWS if row[1] == "PS2508")
    monkeypatch.setattr(study_module, "WINDOWS", (case,))
    market = SimpleNamespace(session_windows=lambda *, symbol, trading_day: [SimpleNamespace(
        start=datetime.fromisoformat(f"{trading_day.isoformat()}T09:00:00+08:00"),
    )])
    calls = []

    def read(session, market, symbol, contract, period, step, days):
        calls.extend(days)
        start = datetime.fromisoformat(f"{days[0].isoformat()}T09:00:00+08:00")
        return [SimpleNamespace(bar_end=start + i * step, open=Decimal(100), high=Decimal(102),
                                low=Decimal(99), close=Decimal(101))
                for i in range(1, 6 if period == "1m" else 2)]

    monkeypatch.setattr(study_module, "read_session_series", read)
    result = study_module.study(None, market, ())["cases"][case[0]]
    assert calls == [date(2025, 7, 17)] * 2
    assert result["status"] == "WINDOW_READABLE"
    assert [item["needed_before_cutoff"] for item in result["coverage"]] == [True, True, False, False]
