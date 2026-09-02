from __future__ import annotations

import json
from pathlib import Path

from guiyi_quant.indicators import initial_sma_state, step_sma
from guiyi_quant.indicators.subing_ths import SubingThs15mKernel


_GOLDEN_PATH = (
    Path(__file__).resolve().parents[3]
    / "tests"
    / "fixtures"
    / "subing_ths_15m_v1_golden.json"
)


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


def test_subing_ths_kernel_freezes_formula_identity() -> None:
    kernel = SubingThs15mKernel()

    assert kernel.formula_version == "subing_ths_15m_v2"
    assert kernel.fast == 12
    assert kernel.slow == 26
    assert kernel.signal == 9
    assert kernel.ema_period == 21
    assert kernel.ema_seed_policy == "sma_window"
    assert kernel.histogram_scale == 2
    assert kernel.round_digits == 6


def test_subing_ths_kernel_invalid_input_breaks_cross_continuity() -> None:
    kernel = SubingThs15mKernel()
    state = kernel.initial_state()
    for index in range(40):
        state, _ = kernel.step(state, 100.0, bar_end=f"bar-{index}")

    state, invalid = kernel.step(state, None, bar_end="invalid")
    assert invalid.ready is False
    assert invalid.valid is False
    assert invalid.reason == "input_invalid"
    assert invalid.result_codes == ()

    for index in range(1, kernel.ema_period + 1):
        state, after_break = kernel.step(state, 101.0, bar_end=f"after-break-{index}")
        if index < kernel.ema_period:
            assert after_break.ready is False
            assert after_break.valid is False
            assert after_break.reason == "input_invalid"
            assert after_break.result_codes == ()

    assert after_break.ready is False
    assert after_break.valid is True
    assert after_break.reason == "warming_up"
    assert after_break.result_codes == ()


def test_subing_ths_kernel_matches_literal_golden_fixture() -> None:
    fixture = json.loads(_GOLDEN_PATH.read_text(encoding="utf-8"))
    kernel = SubingThs15mKernel()
    state = kernel.initial_state()
    actual: list[dict[str, object]] = []

    for bar in fixture["bars"]:
        state, result = kernel.step(state, bar["close"], bar_end=bar["bar_end"])
        actual.append(
            {
                "bar_end": result.bar_end,
                "close": bar["close"],
                "ready": result.ready,
                "valid": result.valid,
                "reason": result.reason,
                "dif": result.dif,
                "dea": result.dea,
                "macd": result.macd,
                "ema21": result.ema21,
                "result_codes": list(result.result_codes),
            }
        )

    assert fixture["formula_version"] == kernel.formula_version
    assert fixture["parameters"] == {
        "fast": kernel.fast,
        "slow": kernel.slow,
        "signal": kernel.signal,
        "ema_period": kernel.ema_period,
        "ema_seed_policy": kernel.ema_seed_policy,
        "histogram_scale": kernel.histogram_scale,
        "round_digits": kernel.round_digits,
    }
    assert actual == fixture["bars"]


def test_subing_ths_kernel_is_prefix_invariant_and_deterministic() -> None:
    fixture = json.loads(_GOLDEN_PATH.read_text(encoding="utf-8"))
    bars = fixture["bars"]
    prefix_length = fixture["prefix_length"]

    def run(input_bars: list[dict[str, object]]) -> list[object]:
        kernel = SubingThs15mKernel()
        state = kernel.initial_state()
        results: list[object] = []
        for bar in input_bars:
            state, result = kernel.step(
                state,
                bar["close"],  # type: ignore[arg-type]
                bar_end=bar["bar_end"],  # type: ignore[arg-type]
            )
            results.append(result)
        return results

    assert run(bars[:prefix_length]) == run(bars)[:prefix_length]
    assert run(bars) == run(bars)
