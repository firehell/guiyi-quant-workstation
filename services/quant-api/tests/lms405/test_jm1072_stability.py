from datetime import timedelta
from decimal import Decimal

import pytest
from guiyi_quant.lms405 import Bar
from lms405_jm1072_stability import evaluate_context
from lms405_right_side_study import US, at


@pytest.mark.parametrize(("side", "earlier", "equal_edge", "price"), [
    ("LONG", 106, 105, 107),
    ("SHORT", 104, 105, 103),
])
def test_prior_close_can_qualify_without_a_current_run_before_shape(side, earlier, equal_edge, price):
    def candle(clock, close):
        end = at(f"2025-11-27T{clock}")
        price = Decimal(close)
        return Bar("JM2601", end, price, price, price, price, start=end - timedelta(minutes=1))

    minutes = [candle("09:13", earlier), candle("09:14", equal_edge), candle("09:15", price)]
    start, confirmed = minutes[0].start, minutes[-1].end
    event = dict(close=Decimal(price), shape_start=at("2025-11-27T09:13"),
                 confirmed_at=confirmed, available_at=confirmed + US)
    band = (Decimal(105), Decimal(110)) if side == "LONG" else (Decimal(100), Decimal(105))
    scope = dict(start=start, side=side, band=band)
    row = evaluate_context(event, {1: minutes, 15: []}, [(start, confirmed)], **scope)
    eligible = row["eligible_as_hypothesis"]
    assert row["price"]["earlier_near_close"] == minutes[0].end
    assert row["price"]["current_run_close_count"] == 1
    assert eligible["earlier_near_close_and_current_beyond"] is True
    assert eligible["same_run_known_before_shape_and_current_beyond"] is False
    assert eligible["earlier_far_close_and_current_beyond"] is False
    assert eligible["near_and_continuous_session_before_confirmation_strict_two_in_sequence"] is None
    assert evaluate_context(event, {1: minutes + [candle("09:16", 95)], 15: []},
                            [(start, confirmed)], **scope) == row


def test_current_confirmation_bar_does_not_supply_an_earlier_cross_or_own_volatility():
    close_time = at("2025-11-27T09:15")
    start = close_time - timedelta(minutes=15)
    price, edge = Decimal(1071), Decimal(1072)
    minute = Bar("JM2601", close_time, edge, edge, price, price, start=close_time - timedelta(minutes=1))
    quarter = Bar("JM2601", close_time, edge, edge, price, price, start=start)
    event = dict(close=price, shape_start=minute.start, confirmed_at=close_time, available_at=close_time + US)
    row = evaluate_context(event, {1: [minute], 15: [quarter]}, [(start, close_time)],
                           start=start, side="SHORT", band=(Decimal(1061), edge))
    assert row["price"]["earlier_near_close"] is None
    assert row["price"]["current_run_close_count"] == 1
    assert row["before_confirmation"] == {"trading_day": None, "continuous_session": None}
    assert not any(row["eligible_as_hypothesis"].values())
