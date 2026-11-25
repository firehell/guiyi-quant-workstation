from decimal import Decimal
from types import SimpleNamespace

from lms405_m_permission_study import compare_paths, completed_paths
from lms405_right_side_study import FIVE, ONE, US, at


def at_minute(value):
    return at(f"2026-10-23T09:{value:02d}")


def minute(end, close):
    return SimpleNamespace(start=at_minute(end) - ONE, end=at_minute(end), close=Decimal(close))


def test_directional_close_path_resets_on_equality_and_continuity_gap():
    bars = [minute(1, "99"), minute(2, "99"), minute(3, "100"),
            minute(4, "99"), minute(7, "99"), minute(8, "101")]
    result = completed_paths(bars, Decimal("100"), "SHORT")
    assert list(result.values()) == [
        (at_minute(1), at_minute(1)), (at_minute(1), at_minute(1)),
        (at_minute(1), None), (at_minute(1), at_minute(4)),
        (at_minute(1), at_minute(7)), (at_minute(1), None),
    ]
    assert result[at_minute(7)] == completed_paths(bars[:-1], Decimal("100"), "SHORT")[at_minute(7)]


def test_confirmation_bar_cannot_start_the_run_for_its_earlier_shape(monkeypatch):
    shape_end = at_minute(10)
    first_confirmation = at_minute(11)
    later_confirmation = at_minute(16)
    qualifying_confirmation = at_minute(22)
    quotes = [minute(i, "100" if i == 10 else "102") for i in range(1, 23)]

    def events(series, shape, confirmation, *, start, as_of, side):
        return [
            dict(shape_end=confirmed - ONE, confirmed_at=confirmed, close=Decimal("102"))
            for confirmed in (first_confirmation, later_confirmation, qualifying_confirmation)
            if confirmed + US < as_of
        ] if confirmation == 1 else []

    monkeypatch.setattr("lms405_m_permission_study.geometry_events", events)
    args = dict(start=at_minute(0), side="LONG", level=Decimal("100"),
                band=(Decimal("100"), Decimal("105")))
    first, later, qualifying = compare_paths({1: quotes}, cutoff=at_minute(23), **args)["events"]["5m_to_1m"]
    assert first["shape_end"] == shape_end
    assert first["after_first_break"] and first["confirmation_inside_m_band"]
    assert first["current_unbroken_run_at"] == first_confirmation
    assert not first["after_current_unbroken_run"]
    assert later["shape_end"] - FIVE == at_minute(10)
    assert not later["after_current_unbroken_run"]
    assert qualifying["after_current_unbroken_run"]
    prefix = compare_paths({1: quotes[:15]}, cutoff=later_confirmation + US, **args)
    assert prefix["events"]["5m_to_1m"] == [first]
