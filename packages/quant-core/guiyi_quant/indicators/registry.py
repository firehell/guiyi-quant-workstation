from __future__ import annotations

from types import MappingProxyType

from .models import IndicatorDefinition, build_indicator_definition


_ALL_INTERVALS = ("1m", "5m", "15m", "30m", "60m", "1d", "1w")

_INDICATOR_ALIASES = {
    "huo_tian_da_you": "huotian_dayou_original_v0",
}


# Source-owned policies. Common analysis is registered in guiyi_quant.compute.
_REGISTRY: dict[str, IndicatorDefinition] = {
    "range_detector_lux_v1": build_indicator_definition(
        indicator_code="range_detector_lux_v1",
        indicator_version="v1",
        display_name="箱体识别（Lux Range）",
        display_type="overlay",
        input_fields=("high", "low", "close"),
        supported_intervals=_ALL_INTERVALS,
        default_parameters={
            "minimum_range_length": 20,
            "range_width_atr_multiplier": 1.0,
            "range_atr_length": 500,
            "source": "close",
            "atr_smoothing_policy": "wilder_sma_seed",
            "round_digits": 6,
        },
        lookback_bars=500,
        warmup_bars=499,
        calculation_source=(
            "guiyi_quant.indicators.range_detector_lux.range_detector_lux_series"
        ),
        closed_bar_only=True,
        confirmed_only=True,
        status="strategy_candidate",
        repainting_risk="none",
        repainting_notes=(
            "Kernel outputs are append-only and causal; Web may retrospectively draw "
            "the confirmed box from visual_start_at without making it strategy-visible."
        ),
        web_capable=True,
        backtest_capable=True,
        live_capable=False,
        alert_capable=False,
        default_visible=False,
        default_color="#2563EB",
        output_schema="channel",
        formal_policy_id="range_detector_lux_v1",
        seed_policy=None,
        smoothing_policy="wilder_sma_seed",
        histogram_scale=None,
    ),
    "huotian_dayou_original_v0": build_indicator_definition(
        indicator_code="huotian_dayou_original_v0",
        indicator_version="original-v0",
        display_name="火天大有（原始观察）",
        display_type="overlay",
        input_fields=("open", "high", "low", "close", "volume"),
        supported_intervals=_ALL_INTERVALS,
        default_parameters={"period": 25},
        lookback_bars=25,
        warmup_bars=24,
        calculation_source="guiyi_quant.indicators.htdy_original.compute_htdy_original",
        closed_bar_only=False,
        confirmed_only=False,
        status="observation_only",
        repainting_risk="known",
        repainting_notes=(
            "Original production XMA uses symmetric clipped windows and can repaint. "
            "Allowed for Web observation and current-bar Alert observation. "
            "Forbidden for historical backtest, formal strategy/live-trading evaluation, and auto-order."
        ),
        web_capable=True,
        backtest_capable=False,
        live_capable=False,
        alert_capable=True,
        default_visible=False,
        default_color="#fb923c",
        output_schema="channel",
        formal_policy_id="huotian_dayou_original_v0",
        seed_policy=None,
        smoothing_policy=None,
        histogram_scale=None,
    ),
}

indicator_registry = MappingProxyType(_REGISTRY)


def resolve_indicator_code(indicator_code: str) -> str:
    return _INDICATOR_ALIASES.get(indicator_code, indicator_code)


def get_indicator(indicator_code: str) -> IndicatorDefinition:
    resolved = resolve_indicator_code(indicator_code)
    try:
        return indicator_registry[resolved]
    except KeyError as exc:
        raise KeyError(f"unknown indicator_code: {indicator_code}") from exc
