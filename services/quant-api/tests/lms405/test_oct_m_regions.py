from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace

from lms405_oct_m_regions import FIVE, LOCAL, NIGHT_POST, ONE, PLAN_POST, measure, split_scope


def bar(hour, minute, *, high="1513", close="1513"):
    return SimpleNamespace(
        bar_end=datetime(2026, 10, 27, hour, minute, tzinfo=LOCAL),
        high=Decimal(high), close=Decimal(close), low=Decimal("1490"),
    )


def test_contact_does_not_count_as_strict_close():
    minutes = [bar(21, 1), bar(21, 2, high="1515", close="1514")]
    fives = [bar(21, 5)]
    result = measure(minutes, fives, {"m": (1513, 1523)})
    assert result["levels"]["m"]["lower"] == {
        "price": "1513",
        "first_1m_high_at_or_above": "2026-10-27T21:01+08:00",
        "first_1m_close_strictly_above": "2026-10-27T21:02+08:00",
        "first_5m_close_strictly_above": None,
    }
    assert result["levels"]["m"]["upper"]["first_1m_high_at_or_above"] is None


def test_scope_excludes_publication_minutes_and_overlap():
    early, first, in_scope, on_cut = bar(17, 39), bar(17, 40), bar(22, 11), bar(22, 12)
    assert split_scope([early, first, in_scope, on_cut], ONE, PLAN_POST.date(), NIGHT_POST) == [first, in_scope]
    partial, contained = bar(17, 40), bar(17, 45)
    assert split_scope([partial, contained], FIVE, PLAN_POST.date(), NIGHT_POST) == [contained]
