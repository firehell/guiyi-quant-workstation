from decimal import Decimal

from guiyi_quant.lms405 import Bar
from lms405_right_side_study import ONE, US, at
from lms405_sh_recovery_progress import CONTRACT, target_clocks, target_gate


def test_sh_prior_touch_cannot_fill_fresh_close_or_current_run():
    start = at("2026-10-27T14:19")
    touch = Bar(CONTRACT, start + ONE, *map(Decimal, (1500, 1502, 1498, 1498)), start=start)
    close = Bar(CONTRACT, start + 2 * ONE, *map(Decimal, (1498, 1500, 1496, 1497)), start=start + ONE)
    price = Decimal(1498)
    history = target_clocks([touch], price)
    current = target_clocks([touch, close], price)
    assert history == {"first_reach": touch.end + US, "first_strict_close": None}
    assert current["first_strict_close"] == close.end + US
    gates = target_gate(close.end + US, history=history, current=current, current_run_start=close.end + US)
    assert gates == dict(historical_reach=True, new_reach_after_snapshot=True,
                         new_strict_close_after_snapshot=False, current_strict_run_started_before_shape=False)
    gates_after_return = target_gate(close.end + 2 * US, history=history, current=current, current_run_start=None)
    assert gates_after_return["new_strict_close_after_snapshot"] is True
    assert gates_after_return["current_strict_run_started_before_shape"] is False
