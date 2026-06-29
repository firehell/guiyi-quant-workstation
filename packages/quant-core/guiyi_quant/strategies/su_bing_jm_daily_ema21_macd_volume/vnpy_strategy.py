from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import date, datetime
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
from typing import Any

from .config_schema import DEFAULT_PARAMS, SuBingJmDailyEma21MacdVolumeParams, validate_params

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
    "guiyi_quant.strategies.su_bing_jm_daily_ema21_macd_volume.vnpy_strategy."
    "SuBingJmDailyEma21MacdVolumeStrategy"
)


@dataclass(frozen=True)
class IndicatorSnapshot:
    ema21: float
    fast_ema: float
    slow_ema: float
    dif: float
    dea: float
    histogram: float
    previous_dif: float
    previous_dea: float
    current_volume: float
    previous_volume: float
    close: float
    near_zero: bool
    golden_cross: bool
    dead_cross: bool
    volume_expanded: bool


@dataclass(frozen=True)
class TradeParams:
    price_tick: float
    contract_multiplier: int
    commission_rate: float | None
    commission_per_contract: float | None
    margin_rate: float
    symbol: str
    exchange: str


@dataclass(frozen=True)
class SignalDecision:
    direction: str
    reason: str
    indicators: IndicatorSnapshot | None = None
    rejected_reason: str | None = None


@dataclass(frozen=True)
class PendingOrder:
    action: str
    direction: str
    signal_datetime: datetime
    signal_bar_index: int
    reason: str
    trade_params: TradeParams
    indicators: IndicatorSnapshot


@dataclass
class PositionState:
    direction: str
    entry_datetime: datetime
    entry_signal_datetime: datetime
    entry_price: float
    entry_bar_index: int
    entry_reason: str
    trade_params: TradeParams
    entry_indicators: IndicatorSnapshot


@dataclass(frozen=True)
class StrategyTrade:
    trade_id: str
    strategy_code: str
    strategy_version: str
    product: str
    symbol: str
    exchange: str
    interval: str
    direction: str
    signal_datetime: str
    fill_datetime: str
    exit_signal_datetime: str
    exit_fill_datetime: str
    entry_price: float
    exit_price: float
    entry_reason: str
    exit_reason: str
    ema21: float
    current_dif: float
    current_dea: float
    previous_dif: float
    previous_dea: float
    current_volume: float
    previous_volume: float
    volume: int
    contract_multiplier: int
    price_tick: float
    commission: float
    slippage: float
    gross_pnl: float
    net_pnl: float
    margin_required: float
    margin_rate: float
    holding_bars: int
    holding_trading_days: int
    holding_calendar_days: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class SuBingJmDailyEma21MacdVolumeStrategy(CtaTemplate):
    author = "guiyi_quant"
    parameters = list(DEFAULT_PARAMS)
    variables = [
        "last_signal",
        "signal_reason",
        "pending_action",
        "position_direction",
        "entry_reason",
        "exit_reason",
        "entry_price",
        "ema21",
        "dif",
        "dea",
        "histogram",
        "current_volume",
        "previous_volume",
    ]

    def __init__(self, cta_engine: Any, strategy_name: str, vt_symbol: str, setting: dict[str, Any]) -> None:
        super().__init__(cta_engine, strategy_name, vt_symbol, setting)
        strategy_setting = {key: value for key, value in setting.items() if not key.startswith("_guiyi_")}
        self._explicit_none_trade_params = {
            key
            for key in ("price_tick", "contract_multiplier", "commission_rate", "commission_per_contract", "margin_rate")
            if key in strategy_setting and strategy_setting[key] is None
        }
        self._params: SuBingJmDailyEma21MacdVolumeParams = validate_params(strategy_setting)
        for name, value in self._params.to_dict().items():
            setattr(self, name, value)

        self._bars: list[Any] = []
        self._pending_order: PendingOrder | None = None
        self._position_state: PositionState | None = None
        self.strategy_trades: list[dict[str, Any]] = []
        self.execution_events: list[dict[str, Any]] = []
        self.rejected_signals: list[dict[str, Any]] = []

        self.last_signal = "none"
        self.signal_reason = "not_started"
        self.pending_action = ""
        self.position_direction = "flat"
        self.entry_reason = ""
        self.exit_reason = ""
        self.entry_price = 0.0
        self.ema21 = 0.0
        self.dif = 0.0
        self.dea = 0.0
        self.histogram = 0.0
        self.current_volume = 0.0
        self.previous_volume = 0.0

    def on_init(self) -> None:
        self.write_log("Su Bing JM daily EMA21 MACD volume strategy initialized")

    def on_start(self) -> None:
        self.write_log("Su Bing JM daily EMA21 MACD volume strategy started")

    def on_stop(self) -> None:
        self.write_log("Su Bing JM daily EMA21 MACD volume strategy stopped")

    def on_bar(self, bar: Any) -> None:
        if not _is_daily_bar(bar):
            self._reject_signal(bar, "non_daily_bar_rejected")
            self.put_event()
            return

        bar_index = len(self._bars)
        closed_this_bar = self._execute_pending_order(bar, bar_index)
        self._bars.append(bar)

        if not closed_this_bar and self._position_state is not None and self._pending_order is None:
            self._schedule_exit_if_required(bar, bar_index)
        if not closed_this_bar and self._position_state is None and self._pending_order is None:
            self._schedule_entry_if_available(bar, bar_index)
        self.put_event()

    def _execute_pending_order(self, bar: Any, bar_index: int) -> bool:
        order = self._pending_order
        if order is None:
            self.pending_action = ""
            return False

        self._pending_order = None
        self.pending_action = ""
        open_price = _bar_float(bar, "open_price", "open")
        fill_time = _bar_datetime(bar)

        if order.action in {"open_long", "open_short"}:
            entry_price = _entry_fill_price(open_price, order.direction, order.trade_params, self._params)
            self._position_state = PositionState(
                direction=order.direction,
                entry_datetime=fill_time,
                entry_signal_datetime=order.signal_datetime,
                entry_price=entry_price,
                entry_bar_index=bar_index,
                entry_reason=order.reason,
                trade_params=order.trade_params,
                entry_indicators=order.indicators,
            )
            self.position_direction = order.direction
            self.entry_price = entry_price
            self.entry_reason = order.reason
            self.last_signal = order.direction
            self.signal_reason = f"filled_next_daily_open|{order.reason}"
            self.execution_events.append(
                {
                    "action": order.action,
                    "signal_datetime": order.signal_datetime.isoformat(),
                    "fill_datetime": fill_time.isoformat(),
                    "fill_price": entry_price,
                    "interval": self._params.interval,
                    "entry_reason": order.reason,
                    "ema21": order.indicators.ema21,
                    "current_dif": order.indicators.dif,
                    "current_dea": order.indicators.dea,
                    "previous_dif": order.indicators.previous_dif,
                    "previous_dea": order.indicators.previous_dea,
                    "current_volume": order.indicators.current_volume,
                    "previous_volume": order.indicators.previous_volume,
                    "price_tick": order.trade_params.price_tick,
                    "contract_multiplier": order.trade_params.contract_multiplier,
                    "margin_rate": order.trade_params.margin_rate,
                }
            )
            return False

        if order.action == "close" and self._position_state is not None:
            exit_price = _exit_fill_price(open_price, self._position_state.direction, order.trade_params, self._params)
            self._close_position(
                bar,
                exit_price=exit_price,
                exit_reason=order.reason,
                exit_signal_datetime=order.signal_datetime,
                exit_indicators=order.indicators,
            )
            return True
        return False

    def _schedule_entry_if_available(self, bar: Any, bar_index: int) -> None:
        if len(self._bars) < _min_bars(self._params):
            self.last_signal = "none"
            self.signal_reason = "warming_up"
            return

        trade_params, missing_reason = self._resolve_trade_params(bar)
        if missing_reason is not None:
            self._reject_signal(bar, missing_reason)
            return

        indicators = calculate_indicators(self._bars, self._params)
        self._set_indicators(indicators)
        decision = decide_signal(indicators, self._params)
        if decision.direction == "none":
            self._reject_signal(bar, decision.rejected_reason or decision.reason)
            return

        assert trade_params is not None
        action = "open_long" if decision.direction == "long" else "open_short"
        self._pending_order = PendingOrder(
            action=action,
            direction=decision.direction,
            signal_datetime=_bar_datetime(bar),
            signal_bar_index=bar_index,
            reason=decision.reason,
            trade_params=trade_params,
            indicators=indicators,
        )
        self.pending_action = action
        self.last_signal = decision.direction
        self.signal_reason = f"signal_on_daily_close_pending_next_daily_open|{decision.reason}"
        self.entry_reason = decision.reason

    def _schedule_exit_if_required(self, bar: Any, bar_index: int) -> None:
        position = self._position_state
        if position is None:
            return
        indicators = calculate_indicators(self._bars, self._params)
        self._set_indicators(indicators)
        close = _bar_float(bar, "close_price", "close")
        reason = ""
        if position.direction == "long" and close < indicators.ema21:
            reason = "long_close_below_ema21_exit_next_daily_open"
        elif position.direction == "short" and close > indicators.ema21:
            reason = "short_close_above_ema21_exit_next_daily_open"
        if not reason:
            return

        self._pending_order = PendingOrder(
            action="close",
            direction=position.direction,
            signal_datetime=_bar_datetime(bar),
            signal_bar_index=bar_index,
            reason=reason,
            trade_params=position.trade_params,
            indicators=indicators,
        )
        self.pending_action = "close"
        self.exit_reason = reason
        self.signal_reason = f"exit_on_daily_close_pending_next_daily_open|{reason}"

    def _close_position(
        self,
        bar: Any,
        *,
        exit_price: float,
        exit_reason: str,
        exit_signal_datetime: datetime,
        exit_indicators: IndicatorSnapshot,
    ) -> None:
        position = self._position_state
        if position is None:
            return
        trade_params = position.trade_params
        exit_time = _bar_datetime(bar)
        volume = self._params.maximum_position
        gross_pnl = _gross_pnl(position.direction, position.entry_price, exit_price, volume, trade_params.contract_multiplier)
        commission = _commission(position.entry_price, exit_price, volume, trade_params)
        slippage = trade_params.price_tick * self._params.slippage_ticks * trade_params.contract_multiplier * volume * 2
        net_pnl = gross_pnl - commission - slippage
        margin_required = position.entry_price * trade_params.contract_multiplier * volume * trade_params.margin_rate
        holding_bars = max(0, len(self._bars) - position.entry_bar_index)
        holding_calendar_days = max(0, (exit_time.date() - position.entry_datetime.date()).days)
        trade = StrategyTrade(
            trade_id=f"SB-JM-D-{len(self.strategy_trades) + 1}",
            strategy_code=self._params.strategy_code,
            strategy_version=self._params.strategy_version,
            product=self._params.product,
            symbol=trade_params.symbol,
            exchange=trade_params.exchange,
            interval=self._params.interval,
            direction=position.direction,
            signal_datetime=position.entry_signal_datetime.isoformat(),
            fill_datetime=position.entry_datetime.isoformat(),
            exit_signal_datetime=exit_signal_datetime.isoformat(),
            exit_fill_datetime=exit_time.isoformat(),
            entry_price=position.entry_price,
            exit_price=exit_price,
            entry_reason=position.entry_reason,
            exit_reason=exit_reason,
            ema21=position.entry_indicators.ema21,
            current_dif=position.entry_indicators.dif,
            current_dea=position.entry_indicators.dea,
            previous_dif=position.entry_indicators.previous_dif,
            previous_dea=position.entry_indicators.previous_dea,
            current_volume=position.entry_indicators.current_volume,
            previous_volume=position.entry_indicators.previous_volume,
            volume=volume,
            contract_multiplier=trade_params.contract_multiplier,
            price_tick=trade_params.price_tick,
            commission=commission,
            slippage=slippage,
            gross_pnl=gross_pnl,
            net_pnl=net_pnl,
            margin_required=margin_required,
            margin_rate=trade_params.margin_rate,
            holding_bars=holding_bars,
            holding_trading_days=holding_bars,
            holding_calendar_days=holding_calendar_days,
        )
        self.strategy_trades.append(trade.to_dict())
        self.execution_events.append(
            {
                "action": "close",
                "exit_reason": exit_reason,
                "signal_datetime": exit_signal_datetime.isoformat(),
                "fill_datetime": exit_time.isoformat(),
                "exit_price": exit_price,
                "interval": self._params.interval,
                "ema21": exit_indicators.ema21,
                "current_dif": exit_indicators.dif,
                "current_dea": exit_indicators.dea,
            }
        )
        self.exit_reason = exit_reason
        self.last_signal = "flat"
        self.signal_reason = f"position_closed|{exit_reason}"
        self.position_direction = "flat"
        self._position_state = None

    def _resolve_trade_params(self, bar: Any) -> tuple[TradeParams | None, str | None]:
        price_tick = None if "price_tick" in self._explicit_none_trade_params else _first_optional_float(
            self._params.price_tick,
            _bar_value(bar, "price_tick"),
            _bar_value(bar, "pricetick"),
        )
        multiplier = None if "contract_multiplier" in self._explicit_none_trade_params else _first_optional_int(
            self._params.contract_multiplier,
            _bar_value(bar, "contract_multiplier"),
            _bar_value(bar, "size"),
        )
        commission_rate = None if "commission_rate" in self._explicit_none_trade_params else _first_optional_float(
            self._params.commission_rate,
            _bar_value(bar, "commission_rate"),
        )
        commission_per_contract = (
            None
            if "commission_per_contract" in self._explicit_none_trade_params
            else _first_optional_float(self._params.commission_per_contract, _bar_value(bar, "commission_per_contract"))
        )
        margin_rate = None if "margin_rate" in self._explicit_none_trade_params else _first_optional_float(
            self._params.margin_rate,
            _bar_value(bar, "margin_rate"),
        )
        if price_tick is None or price_tick <= 0:
            return None, "missing_price_tick"
        if multiplier is None or multiplier <= 0:
            return None, "missing_contract_multiplier"
        if commission_rate is None and commission_per_contract is None:
            return None, "missing_commission_rule"
        if margin_rate is None or margin_rate <= 0:
            return None, "missing_margin_rate"
        symbol = str(_bar_value(bar, "symbol") or self.vt_symbol.rsplit(".", 1)[0])
        exchange = str(_bar_value(bar, "exchange") or (self.vt_symbol.rsplit(".", 1)[1] if "." in self.vt_symbol else ""))
        return (
            TradeParams(
                price_tick=float(price_tick),
                contract_multiplier=int(multiplier),
                commission_rate=None if commission_rate is None else float(commission_rate),
                commission_per_contract=None if commission_per_contract is None else float(commission_per_contract),
                margin_rate=float(margin_rate),
                symbol=symbol,
                exchange=exchange,
            ),
            None,
        )

    def _reject_signal(self, bar: Any, reason: str) -> None:
        self.last_signal = "none"
        self.signal_reason = reason
        self.pending_action = ""
        self.rejected_signals.append(
            {
                "rejected_reason": reason,
                "bar_datetime": _safe_bar_datetime(bar),
                "interval": _bar_value(bar, "interval") or _bar_value(bar, "frequency") or self._params.interval,
                "decision_status": "rejected_by_guardrail",
                "rule_source": self._params.strategy_version,
            }
        )

    def _set_indicators(self, indicators: IndicatorSnapshot) -> None:
        self.ema21 = indicators.ema21
        self.dif = indicators.dif
        self.dea = indicators.dea
        self.histogram = indicators.histogram
        self.current_volume = indicators.current_volume
        self.previous_volume = indicators.previous_volume


def calculate_indicators(
    bars: Sequence[Any],
    params: SuBingJmDailyEma21MacdVolumeParams,
) -> IndicatorSnapshot:
    if len(bars) < 2:
        raise ValueError("at least two completed daily bars are required")
    closes = [_bar_float(bar, "close_price", "close") for bar in bars]
    volumes = [_bar_float(bar, "volume") for bar in bars]
    ema_values = _ema_series(closes, params.ema_period)
    fast_ema_values = _ema_series(closes, params.macd_fast)
    slow_ema_values = _ema_series(closes, params.macd_slow)
    dif_values = [fast - slow for fast, slow in zip(fast_ema_values, slow_ema_values, strict=True)]
    dea_values = _ema_series(dif_values, params.macd_signal)
    dif = dif_values[-1]
    dea = dea_values[-1]
    previous_dif = dif_values[-2]
    previous_dea = dea_values[-2]
    current_volume = volumes[-1]
    previous_volume = volumes[-2]
    return IndicatorSnapshot(
        ema21=ema_values[-1],
        fast_ema=fast_ema_values[-1],
        slow_ema=slow_ema_values[-1],
        dif=dif,
        dea=dea,
        histogram=dif - dea,
        previous_dif=previous_dif,
        previous_dea=previous_dea,
        current_volume=current_volume,
        previous_volume=previous_volume,
        close=closes[-1],
        near_zero=abs(dif) <= params.jm_macd_zero_band and abs(dea) <= params.jm_macd_zero_band,
        golden_cross=previous_dif <= previous_dea and dif > dea,
        dead_cross=previous_dif >= previous_dea and dif < dea,
        volume_expanded=current_volume > previous_volume,
    )


def decide_signal(
    indicators: IndicatorSnapshot,
    params: SuBingJmDailyEma21MacdVolumeParams,
) -> SignalDecision:
    if not indicators.near_zero:
        return SignalDecision("none", "macd_not_near_zero", indicators, "macd_not_near_zero")
    if not indicators.volume_expanded:
        return SignalDecision("none", "volume_not_expanded", indicators, "volume_not_expanded")
    if params.allow_short and indicators.close < indicators.ema21 and indicators.dead_cross:
        return SignalDecision(
            "short",
            "daily_close_below_ema21+macd_near_zero_dead_cross+volume_expansion",
            indicators,
        )
    if params.allow_long and indicators.close > indicators.ema21 and indicators.golden_cross:
        return SignalDecision(
            "long",
            "daily_close_above_ema21+macd_near_zero_golden_cross+volume_expansion",
            indicators,
        )
    return SignalDecision("none", "daily_entry_conditions_not_met", indicators, "daily_entry_conditions_not_met")


def _min_bars(params: SuBingJmDailyEma21MacdVolumeParams) -> int:
    return max(params.ema_period, params.macd_fast, params.macd_slow, params.macd_signal) + 2


def _is_daily_bar(bar: Any) -> bool:
    interval = _bar_value(bar, "interval")
    frequency = _bar_value(bar, "frequency")
    value = interval or frequency
    if value is None:
        return True
    normalized = str(getattr(value, "value", value)).strip().lower()
    return normalized in {"1d", "d", "daily", "day"}


def _entry_fill_price(
    open_price: float,
    direction: str,
    trade_params: TradeParams,
    params: SuBingJmDailyEma21MacdVolumeParams,
) -> float:
    slippage = trade_params.price_tick * params.slippage_ticks
    if direction == "long":
        return _round_to_tick(open_price + slippage, trade_params.price_tick, "up")
    return _round_to_tick(open_price - slippage, trade_params.price_tick, "down")


def _exit_fill_price(
    open_price: float,
    direction: str,
    trade_params: TradeParams,
    params: SuBingJmDailyEma21MacdVolumeParams,
) -> float:
    slippage = trade_params.price_tick * params.slippage_ticks
    if direction == "long":
        return _round_to_tick(open_price - slippage, trade_params.price_tick, "down")
    return _round_to_tick(open_price + slippage, trade_params.price_tick, "up")


def _round_to_tick(price: float, tick: float, direction: str) -> float:
    price_decimal = Decimal(str(price))
    tick_decimal = Decimal(str(tick))
    quotient = price_decimal / tick_decimal
    rounding = ROUND_CEILING if direction == "up" else ROUND_FLOOR
    return float((quotient.to_integral_value(rounding=rounding)) * tick_decimal)


def _gross_pnl(direction: str, entry_price: float, exit_price: float, volume: int, multiplier: int) -> float:
    if direction == "long":
        return (exit_price - entry_price) * volume * multiplier
    return (entry_price - exit_price) * volume * multiplier


def _commission(entry_price: float, exit_price: float, volume: int, trade_params: TradeParams) -> float:
    if trade_params.commission_per_contract is not None:
        return trade_params.commission_per_contract * volume * 2
    assert trade_params.commission_rate is not None
    turnover = (entry_price + exit_price) * trade_params.contract_multiplier * volume
    return turnover * trade_params.commission_rate


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


def _safe_bar_datetime(bar: Any) -> str:
    try:
        return _bar_datetime(bar).isoformat()
    except (AttributeError, ValueError):
        return ""


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


def _first_optional_float(*values: Any) -> float | None:
    for value in values:
        if value is not None:
            return float(value)
    return None


def _first_optional_int(*values: Any) -> int | None:
    for value in values:
        if value is not None:
            return int(value)
    return None


def _ema_series(values: Sequence[float], period: int) -> list[float]:
    if not values:
        return []
    alpha = 2 / (period + 1)
    ema_values = [values[0]]
    for value in values[1:]:
        ema_values.append(value * alpha + ema_values[-1] * (1 - alpha))
    return ema_values


SuBingJmDailyEma21MacdVolume = SuBingJmDailyEma21MacdVolumeStrategy
