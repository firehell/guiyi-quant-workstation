from __future__ import annotations

from types import MappingProxyType

from .models import IndicatorDefinition


_ALL_INTERVALS = ("1m", "5m", "15m", "30m", "60m", "1h", "1d", "1w")


def _ema_definition(period: int, *, default_visible: bool, default_color: str) -> IndicatorDefinition:
    return IndicatorDefinition(
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
    )


_REGISTRY = {
    "ema10": _ema_definition(10, default_visible=False, default_color="#facc15"),
    "ema21": _ema_definition(21, default_visible=True, default_color="#38bdf8"),
    "ema60": _ema_definition(60, default_visible=False, default_color="#c084fc"),
    "huo_tian_da_you": IndicatorDefinition(
        indicator_code="huo_tian_da_you",
        indicator_version="web-observation-v0",
        display_name="火天大有",
        display_type="overlay",
        input_fields=("high", "low", "close"),
        supported_intervals=_ALL_INTERVALS,
        default_parameters={"period": 25},
        lookback_bars=25,
        warmup_bars=24,
        calculation_source="apps/quant-web/src/utils/indicators.ts",
        closed_bar_only=False,
        status="observation_only",
        repainting_risk="known",
        repainting_notes="Current Web layer uses XMA-style centered windows; it can repaint and is forbidden for backtest, live evaluator, signal_events, and notification flows.",
        web_capable=True,
        backtest_capable=False,
        live_capable=False,
        alert_capable=False,
        default_visible=False,
        default_color="#fb923c",
        output_schema="channel",
    ),
}

indicator_registry = MappingProxyType(_REGISTRY)


def get_indicator(indicator_code: str) -> IndicatorDefinition:
    try:
        return indicator_registry[indicator_code]
    except KeyError as exc:
        raise KeyError(f"unknown indicator_code: {indicator_code}") from exc
