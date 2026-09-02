from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
QUANT_CORE_ROOT = REPO_ROOT / "packages" / "quant-core"

if str(QUANT_CORE_ROOT) not in sys.path:
    sys.path.insert(0, str(QUANT_CORE_ROOT))


def test_ema_series_matches_web_sma_window_seed_for_ema21() -> None:
    from guiyi_quant.indicators import ema_series

    closes = [float(100 + index) for index in range(40)]
    bar_ends = [f"2026-01-{index + 1:02d}" for index in range(40)]

    result = ema_series(closes, 21, bar_ends=bar_ends)

    assert len(result.points) == len(closes)
    assert result.indicator_code == "ema21"
    assert result.indicator_version == "v1"
    assert result.repainting_risk == "none"
    assert [point.value for point in result.points[:20]] == [None] * 20
    assert result.points[19].ready is False
    assert result.points[19].valid is True
    assert result.points[20].bar_end == "2026-01-21"
    assert result.points[20].ready is True
    assert result.points[20].valid is True
    assert result.points[20].value == 110.0
    assert result.points[-1].value == 129.0


def test_ema_series_supports_registered_periods_with_one_algorithm() -> None:
    from guiyi_quant.indicators import ema_series, get_indicator

    closes = [float(101 + index) for index in range(80)]

    for period, code in [(10, "ema10"), (21, "ema21"), (60, "ema60")]:
        definition = get_indicator(code)
        result = ema_series(closes, period)
        first_ready_index = period - 1

        assert definition.default_parameters["period"] == period
        assert definition.status == "validated"
        assert definition.repainting_risk == "none"
        assert definition.web_capable is True
        assert definition.live_capable is True
        assert definition.alert_capable is False
        assert result.points[first_ready_index].ready is True
        assert result.points[first_ready_index].valid is True
        assert result.points[first_ready_index].value == round(
            sum(closes[:period]) / period, 6
        )


def test_ema_series_rejects_invalid_period_and_bar_alignment() -> None:
    from guiyi_quant.indicators import ema_series

    with pytest.raises(ValueError, match="EMA period must be positive"):
        ema_series([1.0, 2.0], 0)
    with pytest.raises(ValueError, match="EMA period must be positive"):
        ema_series([1.0], -1)
    with pytest.raises(ValueError, match="bar_ends"):
        ema_series([1.0, 2.0], 2, bar_ends=["2026-01-01"])


def test_ema_series_marks_missing_values_invalid_without_zero_fill() -> None:
    from guiyi_quant.indicators import ema_series

    result = ema_series([10.0, 11.0, math.nan, 13.0, 14.0, 15.0], 3)

    assert result.points[2].ready is True
    assert result.points[2].valid is False
    assert result.points[2].value is None
    assert result.points[2].reason == "input_invalid"
    assert result.points[3].reason == "seed_window_invalid"
    assert result.points[5].valid is True
    assert result.points[5].value == 14.0


def test_ema_series_future_tail_does_not_repaint_past_values() -> None:
    from guiyi_quant.indicators import ema_series

    original = [10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0]
    changed_future = [10.0, 20.0, 30.0, 40.0, 500.0, 600.0, 700.0]

    original_result = ema_series(original, 3)
    changed_result = ema_series(changed_future, 3)

    assert original_result.points[3].value == changed_result.points[3].value
    assert original_result.points[4].value != changed_result.points[4].value


def test_ema21_slope_10_uses_endpoint_change_per_bar_in_bps() -> None:
    from guiyi_quant.indicators import ema21_slope_10_bps_per_bar

    assert ema21_slope_10_bps_per_bar(range(100, 110)) == 91.743119
    assert ema21_slope_10_bps_per_bar([109, 108, 107, 106, 105, 104, 103, 102, 101, 100]) == -100.0


@pytest.mark.parametrize(
    "values",
    [
        [1.0] * 9,
        [1.0] * 11,
    ],
)
def test_ema21_slope_10_requires_exactly_ten_values(
    values: list[float],
) -> None:
    from guiyi_quant.indicators import ema21_slope_10_bps_per_bar

    with pytest.raises(ValueError, match="exactly 10 EMA21 values"):
        ema21_slope_10_bps_per_bar(values)


@pytest.mark.parametrize(
    "values",
    [
        [None, *([1.0] * 9)],
        [math.nan, *([1.0] * 9)],
        [math.inf, *([1.0] * 9)],
        [*([1.0] * 9), 0.0],
    ],
)
def test_ema21_slope_10_returns_none_for_invalid_or_zero_current_value(
    values: list[float | None],
) -> None:
    from guiyi_quant.indicators import ema21_slope_10_bps_per_bar

    assert ema21_slope_10_bps_per_bar(values) is None


def test_incremental_ema_matches_batch_seed_reset_rounding_and_warmup() -> None:
    """Catches incremental EMA drifting from the public batch contract."""
    from guiyi_quant.indicators import (
        IndicatorPoint,
        ema_series,
        initial_ema_state,
        step_ema,
    )

    values = [10.125, 11.25, 12.5, 13.75, math.nan, 20.125, 21.25, 22.5]
    bar_ends = [f"bar-{index}" for index in range(len(values))]
    batch = ema_series(values, 3, bar_ends=bar_ends, round_digits=4)
    state = initial_ema_state(3, seed_policy="sma_window", round_digits=4)
    streamed = []

    for value, bar_end in zip(values, bar_ends, strict=True):
        state, point = step_ema(state, value, bar_end=bar_end)
        streamed.append(point)
        assert len(state.seed_values) <= state.period

    assert streamed == batch.points
    assert streamed[0] == IndicatorPoint(
        bar_end="bar-0", value=None, ready=False, valid=True, reason="warming_up"
    )
    assert streamed[2].value == 11.2917
    assert streamed[4] == IndicatorPoint(
        bar_end="bar-4", value=None, ready=True, valid=False, reason="input_invalid"
    )
    assert streamed[5].reason == "seed_window_invalid"
    assert streamed[6].reason == "seed_window_invalid"
    assert streamed[7].value == 21.2917


def test_parameters_hash_is_stable_and_order_independent() -> None:
    from guiyi_quant.indicators import parameters_hash

    left = parameters_hash({"period": 21, "seed_policy": "sma_window"})
    right = parameters_hash({"seed_policy": "sma_window", "period": 21})

    assert left == right
    assert len(left) == 16


def test_htdy_registry_is_observation_only_and_alert_only_capable() -> None:
    from guiyi_quant.indicators import get_indicator

    definition = get_indicator("huo_tian_da_you")

    assert definition.indicator_code == "huotian_dayou_original_v0"
    assert definition.status == "observation_only"
    assert definition.repainting_risk == "known"
    assert definition.web_capable is True
    assert definition.backtest_capable is False
    assert definition.live_capable is False
    assert definition.alert_capable is True
    assert "XMA" in definition.repainting_notes
