from __future__ import annotations

from types import MappingProxyType

from .models import IndicatorDefinition, build_indicator_definition


_ALL_INTERVALS = ("1m", "5m", "15m", "30m", "60m", "1d", "1w")

_INDICATOR_ALIASES = {
    "huo_tian_da_you": "huotian_dayou_original_v0",
}


def _ema_definition(period: int, *, default_visible: bool, default_color: str) -> IndicatorDefinition:
    return build_indicator_definition(
        indicator_code=f"ema{period}",
        indicator_version="v1",
        display_name=f"EMA{period}",
        display_type="overlay",
        input_fields=("close",),
        supported_intervals=_ALL_INTERVALS,
        default_parameters={"period": period, "seed_policy": "sma_window", "round_digits": 6},
        lookback_bars=period,
        warmup_bars=period - 1,
        calculation_source="guiyi_quant.indicators.ema.ema_series",
        closed_bar_only=True,
        confirmed_only=True,
        status="validated",
        repainting_risk="none",
        repainting_notes="Recursive EMA uses current and past closes only; future tail changes do not alter past values.",
        web_capable=True,
        backtest_capable=True,
        live_capable=True,
        alert_capable=False,
        default_visible=default_visible,
        default_color=default_color,
        output_schema="value",
        formal_policy_id="ema_sma_window_v1",
        seed_policy="sma_window",
        smoothing_policy=None,
        histogram_scale=None,
    )


_REGISTRY: dict[str, IndicatorDefinition] = {
    "ema10": _ema_definition(10, default_visible=False, default_color="#facc15"),
    "ema21": _ema_definition(21, default_visible=True, default_color="#38bdf8"),
    "ema60": _ema_definition(60, default_visible=False, default_color="#c084fc"),
    "macd": build_indicator_definition(
        indicator_code="macd",
        indicator_version="v1-draft",
        display_name="MACD",
        display_type="subpane",
        input_fields=("close",),
        supported_intervals=_ALL_INTERVALS,
        default_parameters={
            "fast": 12,
            "slow": 26,
            "signal": 9,
            "ema_seed_policy": "sma_window",
            "histogram_scale": 2,
            "round_digits": 6,
        },
        lookback_bars=33,
        warmup_bars=33,
        calculation_source="guiyi_quant.indicators.macd.macd_series",
        closed_bar_only=True,
        confirmed_only=True,
        status="compatibility_validated",
        repainting_risk="none",
        repainting_notes="Compatibility-validated Web/Market display policy; not strategy-validated and not alert-capable.",
        web_capable=True,
        backtest_capable=False,
        live_capable=False,
        alert_capable=False,
        default_visible=False,
        default_color="#22d3ee",
        output_schema="value",
        formal_policy_id="web_macd_legacy_v1",
        seed_policy="sma_window",
        smoothing_policy=None,
        histogram_scale=2,
    ),
    "atr": build_indicator_definition(
        indicator_code="atr",
        indicator_version="v1-draft",
        display_name="ATR",
        display_type="subpane",
        input_fields=("high", "low", "close"),
        supported_intervals=_ALL_INTERVALS,
        default_parameters={"period": 14, "smoothing_policy": "wilder_sma_seed", "round_digits": 6},
        lookback_bars=14,
        warmup_bars=13,
        calculation_source="guiyi_quant.indicators.atr.atr_series",
        closed_bar_only=True,
        confirmed_only=True,
        status="compatibility_validated",
        repainting_risk="none",
        repainting_notes="Compatibility-validated Web ATR display policy; not strategy-validated and not alert-capable.",
        web_capable=True,
        backtest_capable=False,
        live_capable=False,
        alert_capable=False,
        default_visible=False,
        default_color="#a3e635",
        output_schema="value",
        formal_policy_id="web_atr_wilder_sma_seed_v1",
        seed_policy=None,
        smoothing_policy="wilder_sma_seed",
        histogram_scale=None,
    ),
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
    "huotian_dayou_strict_v1": build_indicator_definition(
        indicator_code="huotian_dayou_strict_v1",
        indicator_version="strict-v1",
        display_name="火天大有（因果改写）",
        display_type="overlay",
        input_fields=("high", "low", "close"),
        supported_intervals=_ALL_INTERVALS,
        default_parameters={"channel_period": 25, "var23_period": 6},
        lookback_bars=73,
        warmup_bars=72,
        calculation_source="guiyi_quant.indicators.htdy_strict.compute_strict_fields",
        closed_bar_only=True,
        confirmed_only=True,
        status="strategy_candidate",
        repainting_risk="none",
        repainting_notes=(
            "Causal trailing double-EMA rewrite; approved for formal historical research input. "
            "It remains strategy_candidate only and is not live/alert capable. "
            "Former vn.py strategy package path retired; Kernel module is the calculation source."
        ),
        web_capable=False,
        backtest_capable=True,
        live_capable=False,
        alert_capable=False,
        default_visible=False,
        default_color="#f97316",
        output_schema="channel",
        formal_policy_id="huotian_dayou_strict_v1",
        seed_policy="sma_window",
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
