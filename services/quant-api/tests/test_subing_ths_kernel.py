from __future__ import annotations

from guiyi_quant.indicators import initial_sma_state, step_sma


def test_sma_warms_then_rolls_exactly() -> None:
    state = initial_sma_state(3, round_digits=6)
    for value in (1.0, 2.0):
        state, point = step_sma(state, value, bar_end=None)
        assert point.ready is False
        assert point.valid is True
        assert point.value is None
        assert point.reason == "warming_up"

    state, point = step_sma(state, 3.0, bar_end=None)
    assert point.ready is True
    assert point.valid is True
    assert point.value == 2.0
    assert point.reason is None

    _state, point = step_sma(state, 6.0, bar_end=None)
    assert point.value == 3.666667


def test_sma_invalid_input_breaks_continuity() -> None:
    state = initial_sma_state(3)
    for value in (1.0, 2.0, 3.0):
        state, _ = step_sma(state, value, bar_end=None)

    state, invalid = step_sma(state, None, bar_end=None)
    assert invalid.ready is False
    assert invalid.valid is False
    assert invalid.reason == "input_invalid"

    _state, next_point = step_sma(state, 4.0, bar_end=None)
    assert next_point.ready is False
    assert next_point.valid is True
    assert next_point.reason == "warming_up"
