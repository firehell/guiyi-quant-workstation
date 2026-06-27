from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import date, datetime
from typing import Any

from .config_schema import DEFAULT_PARAMS, JmV1bFastEntryParams, validate_params

try:
    from vnpy_ctastrategy import CtaTemplate
except ImportError:
    CTA_TEMPLATE_AVAILABLE = False

    class CtaTemplate:  # type: ignore[no-redef]
        """Import-time placeholder used when vn.py CTA is absent."""

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


STRATEGY_CLASS_PATH = (
    "guiyi_quant.strategies.jm_v1b_daily_direction_fast_entry.vnpy_strategy."
    "JmV1bDailyDirectionFastEntryStrategy"
)


@dataclass(frozen=True)
class IndicatorSnapshot:
    ema: float
    dif: float
    dea: float
    atr: float
    volume_average: float
    previous_dif: float
    previous_dea: float


@dataclass(frozen=True)
class DailyDirectionSnapshot:
    direction: str
    trading_day: date | None
    close: float | None
    ema: float | None
    atr: float | None
    dif: float | None
    dea: float | None
    reason: str


@dataclass(frozen=True)
class EntryDecision:
    direction: str
    entry_reason: str
    daily_direction: str
    stop_loss_price: float


@dataclass(frozen=True)
class PendingOrder:
    action: str
    direction: str
    signal_datetime: datetime
    signal_bar_index: int
    reason: str
    daily_direction: str
    stop_loss_price: float
    hold_bars: int = 0


@dataclass
class PositionState:
    direction: str
    entry_datetime: datetime
    entry_price: float
    entry_bar_index: int
    entry_reason: str
    daily_direction: str
    stop_loss_price: float


@dataclass(frozen=True)
class StrategyTrade:
    daily_direction: str
    entry_interval: str
    entry_reason: str
    exit_reason: str
    hold_bars: int
    stop_loss_price: float
    entry_datetime: str
    exit_datetime: str
    entry_price: float
    exit_price: float
    direction: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class JmV1bDailyDirectionFastEntryStrategy(CtaTemplate):
    author = "guiyi_quant"
    parameters = list(DEFAULT_PARAMS)
    variables = [
        "daily_direction",
        "daily_direction_trading_day",
        "daily_direction_reason",
        "entry_interval",
        "entry_reason",
        "exit_reason",
        "hold_bars",
        "stop_loss_price",
        "last_signal",
        "signal_reason",
        "pending_action",
        "position_direction",
    ]

    def __init__(self, cta_engine: Any, strategy_name: str, vt_symbol: str, setting: dict[str, Any]) -> None:
        super().__init__(cta_engine, strategy_name, vt_symbol, setting)
        strategy_setting = {key: value for key, value in setting.items() if not key.startswith("_guiyi_")}
        self._params: JmV1bFastEntryParams = validate_params(strategy_setting)
        for name, value in self._params.to_dict().items():
            setattr(self, name, value)

        self._bars: list[Any] = []
        self._daily_bars: list[Any] = _extract_daily_bars(setting)
        self._daily_snapshot_cache: dict[date, DailyDirectionSnapshot] = {}
        self._pending_order: PendingOrder | None = None
        self._position_state: PositionState | None = None
        self.strategy_trades: list[dict[str, Any]] = []
        self.execution_events: list[dict[str, Any]] = []

        self.daily_direction = "unavailable"
        self.daily_direction_trading_day = ""
        self.daily_direction_reason = "not_started"
        self.entry_interval = self._params.entry_interval
        self.entry_reason = ""
        self.exit_reason = ""
        self.hold_bars = 0
        self.stop_loss_price = 0.0
        self.last_signal = "none"
        self.signal_reason = "not_started"
        self.pending_action = ""
        self.position_direction = "flat"

    def on_init(self) -> None:
        self.write_log("JM V1-B daily direction fast entry strategy initialized")

    def on_start(self) -> None:
        self.write_log("JM V1-B daily direction fast entry strategy started")

    def on_stop(self) -> None:
        self.write_log("JM V1-B daily direction fast entry strategy stopped")

    def on_bar(self, bar: Any) -> None:
        self._bars.append(bar)
        bar_index = len(self._bars) - 1
        self._execute_pending_order(bar, bar_index)
        if self._position_state is not None:
            self._manage_open_position(bar, bar_index)
        if self._position_state is None and self._pending_order is None:
            self._schedule_entry_if_available(bar, bar_index)
        self.put_event()

    def _execute_pending_order(self, bar: Any, bar_index: int) -> None:
        order = self._pending_order
        if order is None:
            self.pending_action = ""
            return

        open_price = _bar_float(bar, "open_price", "open")
        fill_time = _bar_datetime(bar)
        self._pending_order = None
        self.pending_action = ""

        if order.action in {"open_long", "open_short"}:
            if _gap_crosses_stop(order.direction, open_price, order.stop_loss_price):
                self.last_signal = "none"
                self.signal_reason = "entry_invalid_gap_through_stop"
                self.execution_events.append(
                    {
                        "action": "skip_entry",
                        "reason": self.signal_reason,
                        "signal_datetime": order.signal_datetime.isoformat(),
                        "fill_datetime": fill_time.isoformat(),
                        "entry_interval": self._params.entry_interval,
                    }
                )
                return
            self._position_state = PositionState(
                direction=order.direction,
                entry_datetime=fill_time,
                entry_price=open_price,
                entry_bar_index=bar_index,
                entry_reason=order.reason,
                daily_direction=order.daily_direction,
                stop_loss_price=order.stop_loss_price,
            )
            self.position_direction = order.direction
            self.entry_reason = order.reason
            self.stop_loss_price = order.stop_loss_price
            self.last_signal = order.direction
            self.signal_reason = f"filled_next_bar_open|{order.reason}"
            self.execution_events.append(
                {
                    "action": order.action,
                    "signal_datetime": order.signal_datetime.isoformat(),
                    "fill_datetime": fill_time.isoformat(),
                    "fill_price": open_price,
                    "entry_interval": self._params.entry_interval,
                    "entry_reason": order.reason,
                    "daily_direction": order.daily_direction,
                    "stop_loss_price": order.stop_loss_price,
                }
            )
            return

        if order.action == "close" and self._position_state is not None:
            self._close_position(bar, exit_price=open_price, exit_reason=order.reason, hold_bars=order.hold_bars)

    def _manage_open_position(self, bar: Any, bar_index: int) -> None:
        position = self._position_state
        if position is None:
            return
        self.hold_bars = bar_index - position.entry_bar_index + 1
        self.stop_loss_price = position.stop_loss_price

        if _bar_hits_stop(bar, position.direction, position.stop_loss_price):
            self._close_position(
                bar,
                exit_price=position.stop_loss_price,
                exit_reason="stop_loss_atr_or_structure",
                hold_bars=self.hold_bars,
            )
            return

        if self.hold_bars >= self._params.max_hold_bars_max and self._pending_order is None:
            self._schedule_close(bar, "max_hold_bars_exit")

    def _schedule_entry_if_available(self, bar: Any, bar_index: int) -> None:
        min_bars = _min_intraday_bars(self._params)
        if len(self._bars) < min_bars:
            self.last_signal = "none"
            self.signal_reason = "warming_up"
            return

        daily = self._confirmed_daily_snapshot_for_bar(bar)
        self._set_daily_direction(daily)
        if daily.direction not in {"long", "short"}:
            self.last_signal = "none"
            self.signal_reason = f"daily_direction_blocks_entry|{daily.reason}"
            return

        recent_bars = self._bars[-_indicator_window(self._params) :]
        indicators = calculate_indicators(recent_bars, self._params)
        decision = decide_entry(recent_bars, indicators, daily, self._params)
        if decision.direction == "none":
            self.last_signal = "none"
            self.signal_reason = decision.entry_reason
            return

        action = "open_long" if decision.direction == "long" else "open_short"
        self._pending_order = PendingOrder(
            action=action,
            direction=decision.direction,
            signal_datetime=_bar_datetime(bar),
            signal_bar_index=bar_index,
            reason=decision.entry_reason,
            daily_direction=decision.daily_direction,
            stop_loss_price=decision.stop_loss_price,
        )
        self.pending_action = action
        self.last_signal = decision.direction
        self.signal_reason = f"signal_on_close_pending_next_bar_open|{decision.entry_reason}"
        self.entry_reason = decision.entry_reason
        self.stop_loss_price = decision.stop_loss_price
        self._submit_order_for_next_bar(action, bar)

    def _schedule_close(self, bar: Any, reason: str) -> None:
        position = self._position_state
        if position is None:
            return
        self._pending_order = PendingOrder(
            action="close",
            direction=position.direction,
            signal_datetime=_bar_datetime(bar),
            signal_bar_index=len(self._bars) - 1,
            reason=reason,
            daily_direction=position.daily_direction,
            stop_loss_price=position.stop_loss_price,
            hold_bars=self.hold_bars,
        )
        self.pending_action = "close"
        self.exit_reason = reason
        self.signal_reason = f"exit_on_close_pending_next_bar_open|{reason}"
        self._submit_order_for_next_bar("close", bar)

    def _close_position(self, bar: Any, *, exit_price: float, exit_reason: str, hold_bars: int) -> None:
        position = self._position_state
        if position is None:
            return
        exit_time = _bar_datetime(bar)
        trade = StrategyTrade(
            daily_direction=position.daily_direction,
            entry_interval=self._params.entry_interval,
            entry_reason=position.entry_reason,
            exit_reason=exit_reason,
            hold_bars=hold_bars,
            stop_loss_price=position.stop_loss_price,
            entry_datetime=position.entry_datetime.isoformat(),
            exit_datetime=exit_time.isoformat(),
            entry_price=position.entry_price,
            exit_price=exit_price,
            direction=position.direction,
        )
        self.strategy_trades.append(trade.to_dict())
        self.execution_events.append(
            {
                "action": "close",
                "exit_reason": exit_reason,
                "exit_datetime": exit_time.isoformat(),
                "exit_price": exit_price,
                "hold_bars": hold_bars,
                "entry_interval": self._params.entry_interval,
            }
        )
        self.exit_reason = exit_reason
        self.hold_bars = hold_bars
        self.last_signal = "flat"
        self.signal_reason = f"position_closed|{exit_reason}"
        self.position_direction = "flat"
        self._position_state = None

    def _set_daily_direction(self, snapshot: DailyDirectionSnapshot) -> None:
        self.daily_direction = snapshot.direction
        self.daily_direction_trading_day = "" if snapshot.trading_day is None else snapshot.trading_day.isoformat()
        self.daily_direction_reason = snapshot.reason

    def _confirmed_daily_snapshot_for_bar(self, bar: Any) -> DailyDirectionSnapshot:
        trading_day = _bar_trading_day(bar)
        snapshot = self._daily_snapshot_cache.get(trading_day)
        if snapshot is None:
            snapshot = confirmed_daily_direction_snapshot(
                current_bar=bar,
                daily_bars=self._daily_bars,
                params=self._params,
            )
            self._daily_snapshot_cache[trading_day] = snapshot
        return snapshot

    def _submit_order_for_next_bar(self, action: str, bar: Any) -> None:
        if not self._params.submit_vnpy_orders:
            return
        if not _is_vnpy_backtesting_engine(getattr(self, "cta_engine", None)):
            return
        close_price = _bar_float(bar, "close_price", "close")
        chase = self._params.order_price_chase_ticks * self._params.pricetick
        volume = self._params.fixed_size
        try:
            if action == "open_long" and callable(getattr(self, "buy", None)):
                self.buy(close_price + chase, volume)
            elif action == "open_short" and callable(getattr(self, "short", None)):
                self.short(close_price - chase, volume)
            elif action == "close" and self._position_state is not None:
                if self._position_state.direction == "long" and callable(getattr(self, "sell", None)):
                    self.sell(close_price - chase, volume)
                elif self._position_state.direction == "short" and callable(getattr(self, "cover", None)):
                    self.cover(close_price + chase, volume)
        except Exception as exc:  # pragma: no cover - defensive around optional vn.py runtime.
            self.write_log(f"JM V1-B order submission skipped: {exc}")


def calculate_indicators(bars: Sequence[Any], params: JmV1bFastEntryParams) -> IndicatorSnapshot:
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
    return IndicatorSnapshot(
        ema=ema_values[-1],
        dif=dif_values[-1],
        dea=dea_values[-1],
        atr=atr_values[-1],
        volume_average=_volume_average_prior(volumes, params.volume_window),
        previous_dif=dif_values[-2],
        previous_dea=dea_values[-2],
    )


def decide_entry(
    bars: Sequence[Any],
    indicators: IndicatorSnapshot,
    daily: DailyDirectionSnapshot,
    params: JmV1bFastEntryParams,
) -> EntryDecision:
    current = bars[-1]
    previous = bars[-2]
    current_close = _bar_float(current, "close_price", "close")
    previous_high = _bar_float(previous, "high_price", "high")
    previous_low = _bar_float(previous, "low_price", "low")
    current_volume = _bar_float(current, "volume")
    volume_ratio = current_volume / indicators.volume_average if indicators.volume_average > 0 else 0.0
    ema_distance_atr = abs(current_close - indicators.ema) / indicators.atr if indicators.atr > 0 else float("inf")
    if indicators.atr <= 0:
        return EntryDecision("none", "atr_invalid", daily.direction, 0.0)
    if volume_ratio < params.volume_multiplier:
        return EntryDecision("none", "volume_not_confirmed", daily.direction, 0.0)
    if ema_distance_atr > params.max_ema_distance_atr:
        return EntryDecision("none", "ema_distance_too_wide", daily.direction, 0.0)

    recent = bars[-params.pullback_lookback_bars - 1 : -1]
    recent_lows = [_bar_float(bar, "low_price", "low") for bar in recent]
    recent_highs = [_bar_float(bar, "high_price", "high") for bar in recent]
    golden_cross = indicators.previous_dif <= indicators.previous_dea and indicators.dif > indicators.dea
    death_cross = indicators.previous_dif >= indicators.previous_dea and indicators.dif < indicators.dea

    if (
        params.allow_long
        and daily.direction == "long"
        and current_close > indicators.ema
        and min(recent_lows) <= indicators.ema + params.pullback_touch_ema_atr * indicators.atr
        and (current_close > previous_high or golden_cross)
        and (indicators.dif > indicators.dea or golden_cross)
    ):
        return EntryDecision(
            "long",
            "daily_long_ema21_pullback_macd_confirmed",
            daily.direction,
            _initial_stop_price("long", bars, indicators, params),
        )

    if (
        params.allow_short
        and daily.direction == "short"
        and current_close < indicators.ema
        and max(recent_highs) >= indicators.ema - params.pullback_touch_ema_atr * indicators.atr
        and (current_close < previous_low or death_cross)
        and (indicators.dif < indicators.dea or death_cross)
    ):
        return EntryDecision(
            "short",
            "daily_short_ema21_pullback_macd_confirmed",
            daily.direction,
            _initial_stop_price("short", bars, indicators, params),
        )

    return EntryDecision("none", f"{daily.direction}_entry_conditions_not_met", daily.direction, 0.0)


def confirmed_daily_direction_snapshot(
    *,
    current_bar: Any,
    daily_bars: Sequence[Any],
    params: JmV1bFastEntryParams,
) -> DailyDirectionSnapshot:
    current_trading_day = _bar_trading_day(current_bar)
    confirmed = [bar for bar in daily_bars if _bar_trading_day(bar) < current_trading_day]
    min_bars = max(
        params.daily_ema_period,
        params.daily_macd_slow + params.daily_macd_signal,
        params.daily_atr_period,
        params.daily_ema_slope_lookback + 1,
    )
    if len(confirmed) < min_bars:
        return DailyDirectionSnapshot(
            "unavailable",
            None,
            None,
            None,
            None,
            None,
            None,
            "daily_direction_unavailable_confirmed_bars_insufficient",
        )

    closes = [_bar_float(bar, "close_price", "close") for bar in confirmed]
    highs = [_bar_float(bar, "high_price", "high") for bar in confirmed]
    lows = [_bar_float(bar, "low_price", "low") for bar in confirmed]
    ema_values = _ema_series(closes, params.daily_ema_period)
    fast_ema = _ema_series(closes, params.daily_macd_fast)
    slow_ema = _ema_series(closes, params.daily_macd_slow)
    dif_values = [fast - slow for fast, slow in zip(fast_ema, slow_ema, strict=True)]
    dea_values = _ema_series(dif_values, params.daily_macd_signal)
    atr_values = _atr_series(highs, lows, closes, params.daily_atr_period)

    latest = confirmed[-1]
    latest_close = closes[-1]
    latest_ema = ema_values[-1]
    latest_atr = atr_values[-1]
    latest_dif = dif_values[-1]
    latest_dea = dea_values[-1]
    slope = latest_ema - ema_values[-1 - params.daily_ema_slope_lookback]
    slope_threshold = params.daily_ema_slope_min_atr * latest_atr
    ema_distance_atr = abs(latest_close - latest_ema) / latest_atr if latest_atr > 0 else float("inf")

    if latest_atr <= 0:
        direction = "unavailable"
        reason = "daily_atr_invalid"
    elif ema_distance_atr <= params.daily_neutral_ema_band_atr:
        direction = "neutral"
        reason = "daily_close_near_ema21_neutral"
    elif ema_distance_atr > params.daily_max_ema_distance_atr:
        direction = "neutral"
        reason = "daily_close_too_far_from_ema21_no_chase"
    elif abs(slope) <= slope_threshold:
        direction = "neutral"
        reason = "daily_ema21_slope_flat"
    elif latest_close > latest_ema and slope > 0 and latest_dif >= latest_dea:
        direction = "long"
        reason = "confirmed_daily_long_ema21_macd_atr"
    elif latest_close < latest_ema and slope < 0 and latest_dif <= latest_dea:
        direction = "short"
        reason = "confirmed_daily_short_ema21_macd_atr"
    else:
        direction = "neutral"
        reason = "daily_conditions_conflict"

    return DailyDirectionSnapshot(
        direction,
        _bar_trading_day(latest),
        latest_close,
        latest_ema,
        latest_atr,
        latest_dif,
        latest_dea,
        reason,
    )


def _initial_stop_price(
    direction: str,
    bars: Sequence[Any],
    indicators: IndicatorSnapshot,
    params: JmV1bFastEntryParams,
) -> float:
    current_close = _bar_float(bars[-1], "close_price", "close")
    recent = bars[-params.structure_stop_lookback_bars :]
    buffer_price = params.stop_buffer_ticks * params.pricetick
    if direction == "long":
        atr_stop = current_close - indicators.atr * params.stop_loss_atr_multiple
        structure_stop = min(_bar_float(bar, "low_price", "low") for bar in recent) - buffer_price
        return max(atr_stop, structure_stop)
    atr_stop = current_close + indicators.atr * params.stop_loss_atr_multiple
    structure_stop = max(_bar_float(bar, "high_price", "high") for bar in recent) + buffer_price
    return min(atr_stop, structure_stop)


def _bar_hits_stop(bar: Any, direction: str, stop_price: float) -> bool:
    if direction == "long":
        return _bar_float(bar, "low_price", "low") <= stop_price
    return _bar_float(bar, "high_price", "high") >= stop_price


def _gap_crosses_stop(direction: str, open_price: float, stop_price: float) -> bool:
    if direction == "long":
        return open_price <= stop_price
    return open_price >= stop_price


def _min_intraday_bars(params: JmV1bFastEntryParams) -> int:
    return max(
        params.ema_period,
        params.macd_slow + params.macd_signal,
        params.atr_period,
        params.volume_window,
        params.pullback_lookback_bars + 1,
    ) + 1


def _indicator_window(params: JmV1bFastEntryParams) -> int:
    base_window = max(
        params.ema_period,
        params.macd_slow + params.macd_signal,
        params.atr_period,
        params.volume_window,
        params.pullback_lookback_bars + params.structure_stop_lookback_bars,
    )
    return base_window * 6 + 10


def _is_vnpy_backtesting_engine(cta_engine: Any) -> bool:
    if cta_engine is None:
        return False
    engine_class = cta_engine.__class__
    module_name = getattr(engine_class, "__module__", "")
    class_name = getattr(engine_class, "__name__", "")
    return "backtesting" in module_name.lower() or class_name == "BacktestingEngine"


def _volume_average_prior(volumes: Sequence[float], window: int) -> float:
    prior_volumes = [volume for volume in volumes[:-1][-window:] if volume > 0]
    if not prior_volumes:
        return 0.0
    return sum(prior_volumes) / len(prior_volumes)


def _ema_series(values: Sequence[float], period: int) -> list[float]:
    alpha = 2 / (period + 1)
    ema_values = [values[0]]
    for value in values[1:]:
        ema_values.append(value * alpha + ema_values[-1] * (1 - alpha))
    return ema_values


def _atr_series(highs: Sequence[float], lows: Sequence[float], closes: Sequence[float], period: int) -> list[float]:
    true_ranges = [highs[0] - lows[0]]
    for index in range(1, len(closes)):
        true_ranges.append(
            max(
                highs[index] - lows[index],
                abs(highs[index] - closes[index - 1]),
                abs(lows[index] - closes[index - 1]),
            )
        )
    return _ema_series(true_ranges, period)


def _extract_daily_bars(setting: dict[str, Any]) -> list[Any]:
    auxiliary = setting.get("_guiyi_auxiliary_bars")
    if isinstance(auxiliary, dict):
        bars = auxiliary.get("1d") or auxiliary.get("daily") or []
    else:
        bars = []
    return sorted(list(bars), key=lambda bar: (_bar_trading_day(bar), _bar_datetime(bar)))


def _bar_trading_day(bar: Any) -> date:
    value = _bar_value(bar, "trading_day")
    if value is None:
        return _bar_datetime(bar).date()
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def _bar_datetime(bar: Any) -> datetime:
    value = _bar_value(bar, "datetime")
    if value is None:
        raise AttributeError("bar does not include datetime")
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    if hasattr(value, "to_pydatetime"):
        return value.to_pydatetime().replace(tzinfo=None)
    return datetime.fromisoformat(str(value)).replace(tzinfo=None)


def _bar_float(bar: Any, *names: str) -> float:
    for name in names:
        value = _bar_value(bar, name)
        if value is not None:
            return float(value)
    raise AttributeError(f"bar does not include any of: {', '.join(names)}")


def _bar_value(bar: Any, name: str) -> Any:
    if hasattr(bar, name):
        return getattr(bar, name)
    if isinstance(bar, dict) and name in bar:
        return bar[name]
    return None


JmV1bDailyDirectionFastEntry = JmV1bDailyDirectionFastEntryStrategy
