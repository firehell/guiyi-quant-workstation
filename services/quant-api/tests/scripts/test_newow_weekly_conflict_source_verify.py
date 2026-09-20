from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from app.market_data.domain import CanonicalBar
from scripts.newow_weekly_conflict_source_verify import (
    SourceVerifyError,
    classify_conflict_week,
    validate_source_dates,
)


def _bar(day: date, *, turnover: Decimal, volume: Decimal = Decimal("1"), **overrides):
    values = {
        "bar_end": datetime(day.year, day.month, day.day, 7, tzinfo=UTC),
        "trading_day": day,
        "open": Decimal("100"),
        "high": Decimal("110"),
        "low": Decimal("90"),
        "close": Decimal("105"),
        "volume": volume,
        "turnover": turnover,
        "open_interest": Decimal("30"),
    }
    values.update(overrides)
    return CanonicalBar(**values)


def _week_days() -> tuple[date, ...]:
    return (
        date(2024, 10, 21), date(2024, 10, 22), date(2024, 10, 23),
        date(2024, 10, 24), date(2024, 10, 25),
    )


def test_validate_source_dates_stops_on_extra_or_missing_days():
    expected = _week_days()
    validate_source_dates(expected, expected)

    with pytest.raises(SourceVerifyError, match="SOURCE_RESPONSE_EXTRA_DATES"):
        validate_source_dates(expected, (*expected, date(2024, 10, 26)))
    with pytest.raises(SourceVerifyError, match="SOURCE_RESPONSE_MISSING_DATES"):
        validate_source_dates(expected, expected[:-1])
    with pytest.raises(SourceVerifyError, match="SOURCE_RESPONSE_DUPLICATE_DAY"):
        validate_source_dates(expected, (*expected, expected[0]))


def test_classify_provider_matches_d1_not_w1():
    days = _week_days()
    stored_daily = tuple(_bar(day, turnover=Decimal("10")) for day in days)
    provider_daily = stored_daily
    stored_weekly = _bar(days[-1], turnover=Decimal("40"), volume=Decimal("5"))

    result = classify_conflict_week(
        provider_daily=provider_daily,
        stored_daily=stored_daily,
        stored_weekly=stored_weekly,
    )

    assert result["classification"] == "PROVIDER_MATCHES_D1_NOT_W1"
    assert result["repair_target"] == "W1_PARTITION"
    assert result["stop_queue"] is False


def test_classify_stale_d1_when_provider_turnover_differs():
    days = _week_days()
    stored_daily = tuple(_bar(day, turnover=Decimal("10")) for day in days)
    provider_daily = tuple(_bar(day, turnover=Decimal("11")) for day in days)
    stored_weekly = _bar(days[-1], turnover=Decimal("55"), volume=Decimal("5"))

    result = classify_conflict_week(
        provider_daily=provider_daily,
        stored_daily=stored_daily,
        stored_weekly=stored_weekly,
    )

    assert result["classification"] == "PROVIDER_MATCHES_NEITHER_D1_STALE"
    assert result["repair_target"] == "D1_THEN_W1"
    assert result["stop_queue"] is False


def test_classify_inconclusive_when_provider_matches_neither_turnover():
    days = _week_days()
    stored_daily = tuple(_bar(day, turnover=Decimal("10")) for day in days)
    provider_daily = tuple(_bar(day, turnover=Decimal("12")) for day in days)
    stored_weekly = _bar(days[-1], turnover=Decimal("40"), volume=Decimal("5"))

    result = classify_conflict_week(
        provider_daily=provider_daily,
        stored_daily=stored_daily,
        stored_weekly=stored_weekly,
    )

    assert result["classification"] == "INCONCLUSIVE"
    assert result["repair_target"] == "NONE"
    assert result["stop_queue"] is False


def test_classify_stops_when_non_turnover_fields_differ():
    days = _week_days()
    stored_daily = tuple(_bar(day, turnover=Decimal("10")) for day in days)
    provider_daily = tuple(
        _bar(day, turnover=Decimal("10"), close=Decimal("106") if day == days[0] else Decimal("105"))
        for day in days
    )
    stored_weekly = _bar(days[-1], turnover=Decimal("40"), volume=Decimal("5"))

    result = classify_conflict_week(
        provider_daily=provider_daily,
        stored_daily=stored_daily,
        stored_weekly=stored_weekly,
    )

    assert result["classification"] == "INCONCLUSIVE"
    assert result["repair_target"] == "NONE"
    assert result["stop_queue"] is True
    assert result["reason"] == "BEYOND_TURNOVER_ASSUMPTION"
