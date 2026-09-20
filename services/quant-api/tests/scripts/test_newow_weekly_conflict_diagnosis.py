from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from app.market_data.domain import CanonicalBar
from scripts.newow_weekly_conflict_diagnosis import (
    collect_conflict_weeks,
    diagnosis_status,
    field_differences,
)


def _bar(**overrides):
    values = {
        "bar_end": datetime(2026, 9, 4, 7, tzinfo=UTC),
        "trading_day": date(2026, 9, 4),
        "open": Decimal("100.0"),
        "high": Decimal("110.0"),
        "low": Decimal("90.0"),
        "close": Decimal("105.0"),
        "volume": Decimal("12"),
        "turnover": Decimal("1234.50"),
        "open_interest": Decimal("30"),
    }
    values.update(overrides)
    return CanonicalBar(**values)


def test_field_differences_preserve_decimal_precision_and_all_seven_fields():
    stored = _bar()
    aggregate = _bar(
        close=Decimal("105.00"),
        volume=Decimal("13"),
        turnover=None,
        open_interest=Decimal("31.0"),
    )

    result = field_differences(stored, aggregate)

    assert list(result) == [
        "open", "high", "low", "close", "volume", "turnover", "open_interest"
    ]
    assert result["close"] == {
        "stored": "105.0",
        "d1_aggregate": "105.00",
        "stored_exponent": -1,
        "d1_aggregate_exponent": -2,
        "numeric_equal": True,
        "precision_equal": False,
    }
    assert result["volume"]["numeric_equal"] is False
    assert result["turnover"]["stored"] == "1234.50"
    assert result["turnover"]["d1_aggregate"] is None
    assert result["open_interest"]["precision_equal"] is False


def test_diagnosis_status_fails_closed_on_blocked_contract_or_catalog_drift():
    diagnosed = [{"classification": "SOURCE_VERIFICATION_REQUIRED"}] * 20

    assert diagnosis_status(diagnosed, catalog_revision_stable=True) == "diagnosed"
    assert diagnosis_status(
        [*diagnosed[:-1], {"classification": "DIAGNOSIS_BLOCKED"}],
        catalog_revision_stable=True,
    ) == "blocked"
    assert diagnosis_status(diagnosed, catalog_revision_stable=False) == "blocked"


def _week(days: tuple[date, ...], stored_turnover: Decimal, daily_turnover: Decimal):
    daily = tuple(
        _bar(
            bar_end=datetime(day.year, day.month, day.day, 7, tzinfo=UTC),
            trading_day=day,
            volume=Decimal("1"),
            turnover=daily_turnover,
            open_interest=Decimal("30"),
        )
        for day in days
    )
    week_end = datetime(days[-1].year, days[-1].month, days[-1].day, 7, tzinfo=UTC)
    stored = _bar(
        bar_end=week_end,
        trading_day=days[-1],
        volume=Decimal(len(days)),
        turnover=stored_turnover,
        open_interest=Decimal("30"),
    )
    return week_end, days, daily, stored


def test_collect_conflict_weeks_keeps_every_turnover_mismatch_not_only_the_first():
    first_end, first_days, first_daily, first_stored = _week(
        (date(2024, 10, 21), date(2024, 10, 22), date(2024, 10, 23),
         date(2024, 10, 24), date(2024, 10, 25)),
        stored_turnover=Decimal("100"),
        daily_turnover=Decimal("21"),
    )
    second_end, second_days, second_daily, second_stored = _week(
        (date(2024, 10, 28), date(2024, 10, 29), date(2024, 10, 30),
         date(2024, 10, 31), date(2024, 11, 1)),
        stored_turnover=Decimal("200"),
        daily_turnover=Decimal("41"),
    )
    weekly_rows = (
        SimpleNamespace(
            year=2024, month=10, row_count=2, source_quality_sha256=None,
            file_path=Path("part.aaaa.parquet"),
        ),
        SimpleNamespace(
            year=2024, month=11, row_count=1, source_quality_sha256=None,
            file_path=Path("part.bbbb.parquet"),
        ),
    )
    daily_rows = (
        SimpleNamespace(
            year=2024, month=10, row_count=8, source_quality_sha256=None,
            file_path=Path("part.cccc.parquet"),
        ),
        SimpleNamespace(
            year=2024, month=11, row_count=1, source_quality_sha256=None,
            file_path=Path("part.dddd.parquet"),
        ),
    )

    weeks = collect_conflict_weeks(
        weekly_expected=((first_end, first_days[-1]), (second_end, second_days[-1])),
        daily_expected=tuple(
            (datetime(day.year, day.month, day.day, 7, tzinfo=UTC), day)
            for day in (*first_days, *second_days)
        ),
        daily_bars=(*first_daily, *second_daily),
        daily_gaps=(),
        stored_by_end={first_end: first_stored, second_end: second_stored},
        weekly_rows=weekly_rows,
        daily_rows=daily_rows,
    )

    assert [week["iso_week"] for week in weeks] == [43, 44]
    assert weeks[0]["numeric_conflict_fields"] == ["turnover"]
    assert weeks[1]["numeric_conflict_fields"] == ["turnover"]
    assert weeks[0]["daily_trading_days"] == [day.isoformat() for day in first_days]
    assert weeks[1]["cross_month"] is True
    assert weeks[1]["d1_partitions"][0]["file_name"] == "part.cccc.parquet"
    assert weeks[1]["d1_partitions"][1]["file_name"] == "part.dddd.parquet"
