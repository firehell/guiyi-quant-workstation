from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from app.market_data.domain import CanonicalBar
from scripts.newow_weekly_d1_then_w1_repair import (
    RepairError,
    overlay_provider_turnover,
    realign_weekly_turnover,
    require_w1_matches_corrected_week,
)


def _bar(day: date, *, turnover: Decimal, **overrides):
    values = {
        "bar_end": datetime(day.year, day.month, day.day, 7, tzinfo=UTC),
        "trading_day": day,
        "open": Decimal("100"),
        "high": Decimal("110"),
        "low": Decimal("90"),
        "close": Decimal("105"),
        "volume": Decimal("1"),
        "turnover": turnover,
        "open_interest": Decimal("30"),
    }
    values.update(overrides)
    return CanonicalBar(**values)


def test_overlay_replaces_only_stale_turnover_days():
    days = (
        date(2026, 4, 13),
        date(2026, 4, 14),
        date(2026, 4, 15),
        date(2026, 4, 16),
        date(2026, 4, 17),
    )
    month = (
        _bar(date(2026, 4, 10), turnover=Decimal("1")),
        *(_bar(day, turnover=Decimal("10")) for day in days[:-1]),
        _bar(days[-1], turnover=Decimal("4758012050")),
        _bar(date(2026, 4, 20), turnover=Decimal("2")),
    )
    provider = (
        *(_bar(day, turnover=Decimal("10")) for day in days[:-1]),
        _bar(days[-1], turnover=Decimal("4758012000")),
    )

    corrected, changed = overlay_provider_turnover(month, provider)

    assert changed == (days[-1],)
    assert [bar.trading_day for bar in corrected] == [bar.trading_day for bar in month]
    assert corrected[-2].turnover == Decimal("4758012000")
    assert corrected[0].turnover == Decimal("1")
    assert corrected[-1].turnover == Decimal("2")


def test_overlay_rejects_non_turnover_drift():
    day = date(2026, 4, 17)
    month = (_bar(day, turnover=Decimal("50")),)
    provider = (_bar(day, turnover=Decimal("40"), close=Decimal("106")),)

    with pytest.raises(RepairError, match="BEYOND_TURNOVER_ASSUMPTION"):
        overlay_provider_turnover(month, provider)


def test_overlay_rejects_when_nothing_changes():
    day = date(2026, 4, 17)
    month = (_bar(day, turnover=Decimal("40")),)
    provider = (_bar(day, turnover=Decimal("40")),)

    with pytest.raises(RepairError, match="NO_STALE_TURNOVER_DAY"):
        overlay_provider_turnover(month, provider)


def test_require_w1_matches_corrected_week():
    days = (
        date(2026, 4, 13),
        date(2026, 4, 14),
        date(2026, 4, 15),
        date(2026, 4, 16),
        date(2026, 4, 17),
    )
    week = tuple(_bar(day, turnover=Decimal("10")) for day in days)
    weekly = _bar(days[-1], turnover=Decimal("50"), volume=Decimal("5"))
    require_w1_matches_corrected_week(weekly, week)

    with pytest.raises(RepairError, match="W1_TURNOVER_MISMATCH_AFTER_D1"):
        require_w1_matches_corrected_week(
            _bar(days[-1], turnover=Decimal("49"), volume=Decimal("5")),
            week,
        )


def test_realign_sets_weekly_turnover_to_provider_daily_sum():
    days = (date(2024, 10, 21), date(2024, 10, 22), date(2024, 10, 25))
    stored = tuple(_bar(day, turnover=Decimal("10")) for day in days)
    provider = (
        _bar(days[0], turnover=Decimal("10")),
        _bar(days[1], turnover=Decimal("12")),
        _bar(days[2], turnover=Decimal("10")),
    )
    corrected, changed = overlay_provider_turnover(stored, provider)
    weekly = _bar(days[-1], turnover=Decimal("29"), volume=Decimal("3"))

    aligned = realign_weekly_turnover(weekly, corrected)

    assert changed == (days[1],)
    assert aligned.turnover == Decimal("32")
    assert aligned.open == weekly.open
    assert aligned.volume == weekly.volume


def test_realign_rejects_a_weekly_price_mismatch():
    day = date(2024, 10, 25)
    corrected = (_bar(day, turnover=Decimal("10")),)
    weekly = _bar(day, turnover=Decimal("10"), close=Decimal("106"))

    with pytest.raises(RepairError, match="W1_NON_TURNOVER_MISMATCH"):
        realign_weekly_turnover(weekly, corrected)
