"""The OI repair only appends exact missing W1 endpoints to monthly candidates."""

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from app.market_data.domain import CanonicalBar
from scripts.oi_weekly_local_rebuild import MISSING_DAYS, OIRebuildError, _merge_month


def _bar(day: date, *, end: datetime | None = None) -> CanonicalBar:
    return CanonicalBar(
        bar_end=end or datetime(day.year, day.month, day.day, 7, tzinfo=UTC),
        trading_day=day,
        open=Decimal("1"), high=Decimal("2"), low=Decimal("1"), close=Decimal("2"),
        volume=Decimal("3"), turnover=Decimal("4"), open_interest=Decimal("5"),
    )


def test_exact_pinned_scope_excludes_quality_interruption() -> None:
    assert len(MISSING_DAYS) == 37
    assert MISSING_DAYS[0] == date(2025, 11, 28)
    assert MISSING_DAYS[-1] == date(2026, 8, 14)
    assert date(2025, 11, 21) not in MISSING_DAYS


def test_merge_month_handles_absent_and_partially_populated_partitions() -> None:
    aug_7, aug_14, aug_21 = (_bar(date(2026, 8, day)) for day in (7, 14, 21))
    assert _merge_month((), (aug_7, aug_14)) == (aug_7, aug_14)
    assert _merge_month((aug_21,), (aug_14, aug_7)) == (aug_7, aug_14, aug_21)
    assert _merge_month((aug_21,), (aug_14, aug_7))[2] is aug_21


@pytest.mark.parametrize("previous,additions", [
    ((date(2026, 8, 7),), (date(2026, 8, 7),)),
    ((), (date(2026, 8, 7), date(2026, 8, 7))),
])
def test_merge_month_rejects_existing_or_duplicate_week(previous, additions) -> None:
    with pytest.raises(OIRebuildError, match="W1_DUPLICATE_ENDPOINT"):
        _merge_month(tuple(map(_bar, previous)), tuple(map(_bar, additions)))


def test_merge_month_rejects_distinct_end_for_same_trading_day() -> None:
    day = date(2026, 8, 7)
    with pytest.raises(OIRebuildError, match="W1_TARGET_ALREADY_PRESENT"):
        _merge_month((_bar(day),), (_bar(day, end=datetime(2026, 8, 7, 8, tzinfo=UTC)),))
