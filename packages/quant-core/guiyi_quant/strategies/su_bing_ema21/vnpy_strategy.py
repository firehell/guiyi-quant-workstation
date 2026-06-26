from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from .config_schema import DEFAULT_PARAMS, SuBingEma21Params, validate_params

try:
    from vnpy_ctastrategy import CtaTemplate
except ImportError:
    CTA_TEMPLATE_AVAILABLE = False

    class CtaTemplate:  # type: ignore[no-redef]
        """Import-time placeholder used when the CTA strategy package is absent."""

        def __init__(self, cta_engine: Any, strategy_name: str, vt_symbol: str, setting: dict[str, Any]) -> None:
            self.cta_engine = cta_engine
            self.strategy_name = strategy_name
            self.vt_symbol = vt_symbol
            self.setting = setting

        def write_log(self, message: str) -> None:
            self.last_log = message

        def put_event(self) -> None:
            self.last_event_emitted = True

else:
    CTA_TEMPLATE_AVAILABLE = True


@dataclass(frozen=True)
class IndicatorSnapshot:
    ema: float
    dif: float
    dea: float
    atr: float
    volume_average: float


@dataclass(frozen=True)
class SignalDecision:
    direction: str
    reason: str
    note: str
    stop_price: float | None = None
    take_profit_price: float | None = None


class SuBingEma21VnpyStrategy(CtaTemplate):
    author = "guiyi_quant"
    parameters = list(DEFAULT_PARAMS)
    variables = [
        "last_signal",
        "signal_reason",
        "trade_note",
        "ema_value",
        "dif_value",
        "dea_value",
        "atr_value",
        "stop_price",
        "take_profit_price",
    ]

    def __init__(self, cta_engine: Any, strategy_name: str, vt_symbol: str, setting: dict[str, Any]) -> None:
        super().__init__(cta_engine, strategy_name, vt_symbol, setting)
        params = validate_params(setting)
        self._params: SuBingEma21Params = params
        for name, value in params.to_dict().items():
            setattr(self, name, value)

        self._bars: list[Any] = []
        self.last_signal = "none"
        self.signal_reason = "not_started"
        self.trade_note = "waiting_for_completed_bars"
        self.ema_value = 0.0
        self.dif_value = 0.0
        self.dea_value = 0.0
        self.atr_value = 0.0
        self.stop_price = 0.0
        self.take_profit_price = 0.0

    def on_init(self) -> None:
        self.write_log("SuBing EMA21 vn.py strategy draft initialized")

    def on_start(self) -> None:
        self.write_log("SuBing EMA21 signal draft started")

    def on_stop(self) -> None:
        self.write_log("SuBing EMA21 signal draft stopped")

    def on_bar(self, bar: Any) -> None:
        self._bars.append(bar)
        min_bars = max(self.ema_period, self.macd_slow + self.macd_signal, self.atr_period, self.volume_window) + 1
        if len(self._bars) < min_bars:
            self._set_decision(SignalDecision("none", "warming_up", "insufficient_completed_bars"))
            self.put_event()
            return

        indicators = self._calculate_indicators(self._bars, self._params)
        self.ema_value = indicators.ema
        self.dif_value = indicators.dif
        self.dea_value = indicators.dea
        self.atr_value = indicators.atr

        decision = self._decide_signal(self._bars, indicators, self._params)
        self._set_decision(decision)
        self.put_event()

    def _set_decision(self, decision: SignalDecision) -> None:
        self.last_signal = decision.direction
        self.signal_reason = decision.reason
        self.trade_note = decision.note
        self.stop_price = decision.stop_price or 0.0
        self.take_profit_price = decision.take_profit_price or 0.0

    @staticmethod
    def _calculate_indicators(bars: Sequence[Any], params: SuBingEma21Params) -> IndicatorSnapshot:
        closes = [_bar_float(bar, "close_price", "close") for bar in bars]
        highs = [_bar_float(bar, "high_price", "high") for bar in bars]
        lows = [_bar_float(bar, "low_price", "low") for bar in bars]
        volumes = [_bar_float(bar, "volume") for bar in bars]

        ema_values = _ema_series(closes, params.ema_period)
        fast_ema = _ema_series(closes, params.macd_fast)
        slow_ema = _ema_series(closes, params.macd_slow)
        dif_values = [fast - slow for fast, slow in zip(fast_ema, slow_ema, strict=True)]
        dea_values = _ema_series(dif_values, params.macd_signal)
        atr_values = _atr_series(highs, lows, closes, params.atr_period)
        volume_window = volumes[-params.volume_window :]

        return IndicatorSnapshot(
            ema=ema_values[-1],
            dif=dif_values[-1],
            dea=dea_values[-1],
            atr=atr_values[-1],
            volume_average=sum(volume_window) / len(volume_window),
        )

    @staticmethod
    def _decide_signal(bars: Sequence[Any], indicators: IndicatorSnapshot, params: SuBingEma21Params) -> SignalDecision:
        closes = [_bar_float(bar, "close_price", "close") for bar in bars]
        current_close = closes[-1]
        previous_indicators = SuBingEma21VnpyStrategy._calculate_indicators(bars[:-1], params)
        current_volume = _bar_float(bars[-1], "volume")
        has_volume_confirmation = current_volume >= indicators.volume_average * params.volume_multiplier
        ema_distance_atr = abs(current_close - indicators.ema) / indicators.atr if indicators.atr > 0 else 0.0
        near_ema = ema_distance_atr <= params.max_ema_deviation_atr
        near_zero_axis = abs(indicators.dif) <= indicators.atr

        golden_cross = previous_indicators.dif <= previous_indicators.dea and indicators.dif > indicators.dea
        death_cross = previous_indicators.dif >= previous_indicators.dea and indicators.dif < indicators.dea

        if params.allow_long and current_close > indicators.ema and golden_cross and near_ema and near_zero_axis and has_volume_confirmation:
            risk = indicators.atr * params.stop_atr_multiple
            return SignalDecision(
                direction="long",
                reason="ema21_bullish_macd_golden_cross",
                note="completed_bar_long_signal_wait_engine_fill",
                stop_price=current_close - risk,
                take_profit_price=current_close + risk * params.take_profit_r_multiple,
            )

        if params.allow_short and current_close < indicators.ema and death_cross and near_ema and near_zero_axis and has_volume_confirmation:
            risk = indicators.atr * params.stop_atr_multiple
            return SignalDecision(
                direction="short",
                reason="ema21_bearish_macd_death_cross",
                note="completed_bar_short_signal_wait_engine_fill",
                stop_price=current_close + risk,
                take_profit_price=current_close - risk * params.take_profit_r_multiple,
            )

        reasons = []
        if current_close > indicators.ema:
            reasons.append("bullish_environment")
        elif current_close < indicators.ema:
            reasons.append("bearish_environment")
        else:
            reasons.append("neutral_ema21")
        if not has_volume_confirmation:
            reasons.append("volume_not_confirmed")
        if not near_ema:
            reasons.append("ema_distance_too_wide")
        if not near_zero_axis:
            reasons.append("macd_not_near_zero_axis")
        return SignalDecision("none", "|".join(reasons), "completed_bar_no_signal")


def _ema_series(values: Sequence[float], period: int) -> list[float]:
    alpha = 2 / (period + 1)
    ema_values = [values[0]]
    for value in values[1:]:
        ema_values.append(value * alpha + ema_values[-1] * (1 - alpha))
    return ema_values


def _atr_series(highs: Sequence[float], lows: Sequence[float], closes: Sequence[float], period: int) -> list[float]:
    true_ranges = [highs[0] - lows[0]]
    for index in range(1, len(closes)):
        true_ranges.append(max(highs[index] - lows[index], abs(highs[index] - closes[index - 1]), abs(lows[index] - closes[index - 1])))
    return _ema_series(true_ranges, period)


def _bar_float(bar: Any, *names: str) -> float:
    for name in names:
        if hasattr(bar, name):
            return float(getattr(bar, name))
        if isinstance(bar, dict) and name in bar:
            return float(bar[name])
    raise AttributeError(f"bar does not include any of: {', '.join(names)}")
