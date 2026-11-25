from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from lms405_fg_sa_case import at
from lms405_sa_reentry_study import minute_close_geometry, price_compatibility


def minute_bar(time, op, hi, lo, cl):
    open_, high, low, close = map(Decimal, (op, hi, lo, cl))
    return SimpleNamespace(bar_end=at(time), open=open_, high=high, low=low, close=close)


def test_multifill_average_can_be_compatible_without_a_single_minute_containing_it():
    trading_day = date(2026, 10, 26)
    rows = [
        SimpleNamespace(bar_end=at(f"23T{minute}"), trading_day=day, low=Decimal(lo), high=Decimal(hi))
        for minute, day, lo, hi in (
            ("21:00", trading_day, 963, 963),
            ("21:01", trading_day, 959, 962),
            ("21:02", date(2026, 10, 23), 963, 963),
            ("21:03", trading_day, 964, 965),
            ("21:04", trading_day, 963, 963),
        )
    ]
    result = price_compatibility(rows, trading_day, at("23T21:00"), at("23T21:04"), "963")
    assert result["bars"] == 2
    assert result["range"] == ["959", "965"]
    assert result["average_range_compatible"]
    assert result["single_price_compatible_minutes"] == []

    after_signal = price_compatibility(rows, trading_day, at("23T21:01"), at("23T21:04"), "963")
    assert after_signal["range"] == ["964", "965"]
    assert not after_signal["average_range_compatible"]


def test_one_minute_geometry_only_uses_prior_completed_bars():
    rows = [minute_bar(f"26T21:0{minute}", op, hi, lo, cl) for minute, op, hi, lo, cl in (
        (1, 966, 968, 958, 963), (2, 963, 965, 960, 961), (3, 961, 963, 956, 959), (4, 959, 964, 959, 961),
    )]
    night, cut = at("26T21:00"), at("26T21:04")
    assert minute_close_geometry(rows, night, at("26T21:03"), "SHORT") == []
    actual, = minute_close_geometry(rows, night, cut, "SHORT")
    assert [actual] == minute_close_geometry(rows[:3], night, cut, "SHORT")
    assert actual["confirmed_at"] == at("26T21:03")
    assert actual["available_at"] > actual["confirmed_at"]
    assert actual["boundary"] == Decimal(960)


def test_fast_confirmation_does_not_wait_for_following_five_minute_bar():
    fives = [minute_bar("26T21:55", 966, 968, 958, 963), minute_bar("26T22:00", 963, 965, 960, 961)]
    minutes = [minute_bar("26T22:01", 961, 963, 956, 959)]
    actual, = minute_close_geometry(minutes, at("26T21:00"), at("26T22:04"), "SHORT", fives=fives)
    assert actual["shape_end"] == at("26T22:00")
    assert actual["confirmed_at"] == at("26T22:01")
