"""Owned trend measures derived from registered EMA21 and ATR14."""

from math import isfinite

from ..indicators.subing_trend import slope_point
from .contracts import FeaturePoint, Status
from .registry import IndicatorDefinition, FeatureRequest


def _calculate(data, _):
    ema, atr = data.dependencies
    points = []
    for index, ema_point in enumerate(ema.points):
        point = (ema_point.bar_end, ema_point.available_at)
        atr_point = atr.points[index]
        window = ema.points[max(0, index - 4):index + 1]
        dependency = next(
            (item for item in (*window, atr_point) if item.status in (Status.INVALID, Status.UNKNOWN)),
            None,
        )
        if dependency is not None:
            points.append(FeaturePoint(*point, dependency.status, diagnostic=dependency.diagnostic))
        elif len(window) != 5 or any(item.values is None for item in (*window, atr_point)):
            points.append(FeaturePoint(*point, Status.WARMING, diagnostic="LOOKBACK_REQUIRED"))
        else:
            ema_window = tuple(float(item.values["value"]) for item in window)
            trend = slope_point(ema_window, float(atr_point.values["value"]))
            slope = ema_window[-1] - ema_window[-2]
            if trend.reason is not None:
                points.append(FeaturePoint(*point, Status.UNKNOWN, diagnostic=trend.reason))
            elif not all(isfinite(value) for value in (slope, trend.slope, trend.normalized_slope)):
                points.append(FeaturePoint(*point, Status.INVALID, diagnostic="OUTPUT_NONFINITE"))
            else:
                points.append(FeaturePoint(*point, Status.READY, {
                    "direction": trend.direction,
                    "ema21_slope": slope,
                    "ols_slope": trend.slope,
                    "atr_normalized_slope": trend.normalized_slope,
                }))
    return tuple(points), ()


TREND_DEFINITION = IndicatorDefinition(
    feature_id="trend_direction", category="trend", formula_version="guiyi_trend_ema21_ols5_atr14_v1",
    backend_version="guiyi_trend_v1", input_fields=(), parameters={},
    outputs=("direction", "ema21_slope", "ols_slope", "atr_normalized_slope"),
    calculate=_calculate, lookback=lambda _: 24,
    dependencies=(FeatureRequest("ema21"), FeatureRequest("atr")),
)
