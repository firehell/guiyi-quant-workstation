"""The generic indicator whitelist. TA-Lib owns the technical formulas."""

from collections.abc import Callable, Mapping
from functools import partial
from importlib.metadata import version
from math import isfinite, isnan

import numpy as np
import talib
from numpy.lib.stride_tricks import sliding_window_view
from numpy.typing import NDArray
from talib import stream

from .contracts import FeaturePoint, InputField, ParameterValue, Status
from .registry import CalculationInput, IndicatorDefinition, Parameter, first_invalid, input_problem


# Some post releases retain the wrapper's source-level __version__.
TALIB_BACKEND_VERSION = "ta-lib:" + version("ta-lib")
FloatArray = NDArray[np.float64]
ArrayCalculation = Callable[
    [tuple[FloatArray, ...], Mapping[str, ParameterValue]], tuple[FloatArray, ...]
]
_PERIOD = Parameter(None, minimum=2, maximum=100_000)


def require_talib_defaults() -> None:
    if (
        talib.get_compatibility() != 0
        or talib.get_unstable_period("EMA") != 0
        or talib.get_unstable_period("ATR") != 0
    ):
        raise RuntimeError("TA_LIB_GLOBAL_SETTINGS_UNSUPPORTED")


def _one(function: Callable, parameter: str = "timeperiod") -> ArrayCalculation:
    def run(columns, params):
        options = {parameter: params["period"]} if "period" in params else {}
        return (function(*columns, **options),)

    return run


def _macd(columns, params):
    return talib.MACD(
        columns[0], fastperiod=params["fast"], slowperiod=params["slow"],
        signalperiod=params["signal"],
    )


def _stddev(columns, params):
    return (talib.STDDEV(columns[0], timeperiod=params["period"], nbdev=params["nbdev"]),)


def _boll(columns, params):
    return talib.BBANDS(
        columns[0], timeperiod=params["period"], nbdevup=params["upper"],
        nbdevdn=params["lower"], matype=params["matype"],
    )


def _volume_ratio(columns, params):
    (volume,) = columns
    period = int(params["period"])
    output = np.full(volume.size, np.nan, dtype=np.float64)
    if volume.size > period:
        # Summing scaled observations avoids overflow of the reference mean.
        means = sliding_window_view(volume[:-1] / period, period).sum(axis=1)
        with np.errstate(over="ignore"):
            np.divide(volume[period:], means, out=output[period:], where=means > 0)
    return (output,)


def _calculate(
    data: CalculationInput,
    parameters: Mapping[str, ParameterValue],
    *,
    fields: tuple[InputField, ...],
    outputs: tuple[str, ...],
    calculate: ArrayCalculation,
    lookback: Callable[[Mapping[str, ParameterValue]], int],
    uses_talib: bool,
):
    if uses_talib:
        require_talib_defaults()
    prefix = first_invalid(data, fields)
    arrays = calculate(tuple(data.columns[name][:prefix] for name in fields), parameters) if prefix else ()
    first_ready = lookback(parameters)
    points: list[FeaturePoint] = []
    for index, (bar, available_at) in enumerate(zip(data.bars, data.available_at, strict=True)):
        point = (bar.bar_end, available_at)
        if index >= prefix:
            status, reason = input_problem(bar, fields) or (
                Status.UNKNOWN, "INPUT_PREFIX_INTERRUPTED",
            )
            points.append(FeaturePoint(*point, status, diagnostic=reason))
        elif index < first_ready:
            points.append(FeaturePoint(*point, Status.WARMING, diagnostic="LOOKBACK_REQUIRED"))
        else:
            values = tuple(float(array[index]) for array in arrays)
            points.append(_point(bar, available_at, values, outputs, volume_ratio=not uses_talib))
    return tuple(points), ()


def _point(bar, at, output, outputs, *, volume_ratio=False):
    values = output if isinstance(output, tuple) else (output,)
    if all(isfinite(value) for value in values):
        return FeaturePoint(bar.bar_end, at, Status.READY, dict(zip(outputs, values, strict=True)))
    if volume_ratio and isnan(values[0]):
        return FeaturePoint(bar.bar_end, at, Status.UNKNOWN, diagnostic="ZERO_REFERENCE_VOLUME")
    return FeaturePoint(bar.bar_end, at, Status.INVALID, diagnostic="OUTPUT_NONFINITE")


def _definition(
    name: str, fields: tuple[InputField, ...], parameters: Mapping[str, Parameter],
    calculate: ArrayCalculation, lookback: Callable[[Mapping[str, ParameterValue]], int],
    *, outputs: tuple[str, ...] = ("value",), formula: str | None = None, uses_talib: bool = True,
) -> IndicatorDefinition:
    return IndicatorDefinition(
        feature_id=name, category="generic", formula_version=formula or f"talib_{name}_v1",
        backend_version=TALIB_BACKEND_VERSION if uses_talib else f"numpy:{np.__version__}",
        input_fields=fields, parameters=parameters, outputs=outputs, lookback=lookback,
        calculate=partial(
            _calculate, fields=fields, outputs=outputs, calculate=calculate, lookback=lookback,
            uses_talib=uses_talib,
        ),
        modes=frozenset(("batch", "incremental", "live")),
        allowed_uses=frozenset(("web", "research", "backtest", "simulation")),
    )


def _period(params: Mapping[str, ParameterValue]) -> int:
    return int(params["period"])


def _window_lookback(params: Mapping[str, ParameterValue]) -> int:
    return _period(params) - 1


def _fixed(value: int) -> Parameter:
    return Parameter(value, minimum=value, maximum=value)


GENERIC_DEFINITIONS = (
    *(
        _definition(
            f"ema{period}", ("close",), {"period": _fixed(period)}, _one(talib.EMA),
            _window_lookback,
        )
        for period in (10, 21, 60)
    ),
    _definition(
        "macd", ("close",), {"fast": _fixed(12), "slow": _fixed(26), "signal": _fixed(9)},
        _macd, lambda params: int(params["slow"]) + int(params["signal"]) - 2,
        outputs=("dif", "dea", "histogram"), formula="talib_macd_12_26_9_v1",
    ),
    _definition("atr", ("high", "low", "close"), {"period": Parameter(14, 2, 100_000)},
                _one(talib.ATR), _period),
    _definition(
        "stddev", ("close",), {"period": Parameter(20, 2, 100_000), "nbdev": _fixed(1)},
        _stddev, _window_lookback,
    ),
    _definition(
        "boll", ("close",), {
            "period": Parameter(20, 2, 100_000), "upper": Parameter(2, 0.01, 20, integral=False),
            "lower": Parameter(2, 0.01, 20, integral=False), "matype": _fixed(0),
        },
        _boll, _window_lookback, outputs=("upper", "middle", "lower"),
    ),
    _definition("hhv", ("high",), {"period": _PERIOD}, _one(talib.MAX), _window_lookback),
    _definition("llv", ("low",), {"period": _PERIOD}, _one(talib.MIN), _window_lookback),
    _definition("obv", ("close", "volume"), {}, _one(talib.OBV), lambda _: 0),
    _definition(
        "volume_ratio", ("volume",), {"period": Parameter(5, 1, 500)}, _volume_ratio, _period,
        formula="guiyi_volume_ratio_prior_completed_v1", uses_talib=False,
    ),
)


def _stream_options(name: str, params: Mapping[str, ParameterValue]):
    if name.startswith("ema"):
        return stream.EMA, {"timeperiod": params["period"]}
    if name == "macd":
        return stream.MACD, {
            "fastperiod": params["fast"], "slowperiod": params["slow"], "signalperiod": params["signal"],
        }
    if name == "boll":
        return stream.BBANDS, {
            "timeperiod": params["period"], "nbdevup": params["upper"],
            "nbdevdn": params["lower"], "matype": params["matype"],
        }
    if name == "stddev":
        return stream.STDDEV, {"timeperiod": params["period"], "nbdev": params["nbdev"]}
    if name == "obv":
        return stream.OBV, {}
    function = {"atr": stream.ATR, "hhv": stream.MAX, "llv": stream.MIN}[name]
    return function, {"timeperiod": params["period"]}


def open_stream(name: str, params: Mapping[str, ParameterValue], columns: tuple[FloatArray, ...]):
    require_talib_defaults()
    function, options = _stream_options(name, params)
    return function(*columns, **options)
