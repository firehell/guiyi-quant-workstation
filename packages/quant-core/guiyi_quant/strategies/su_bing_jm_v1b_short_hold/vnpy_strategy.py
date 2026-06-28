from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import date, datetime
from typing import Any

from .config_schema import DEFAULT_PARAMS, SuBingJmV1bShortHoldParams, validate_params

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
    "guiyi_quant.strategies.su_bing_jm_v1b_short_hold.vnpy_strategy."
    "SuBingJmV1bShortHoldStrategy"
)


@dataclass(frozen=True)
class IndicatorSnapshot:
    ema: float
    previous_ema: float
    close: float


@dataclass(frozen=True)
class DailyDirectionSnapshot:
    direction: str
    trading_day: date | None
    close: float | None
    ema: float | None
    previous_ema: float | None
    reason: str


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
class EntryDecision:
    direction: str
    entry_reason: str
    daily_direction: str
    stop_loss_price: float
    trade_params: TradeParams | None = None
    rejected_reason: str | None = None


@dataclass(frozen=True)
class PendingOrder:
    action: str
    direction: str
    signal_datetime: datetime
    signal_bar_index: int
    reason: str
    daily_direction: str
    stop_loss_price: float
    trade_params: TradeParams
    holding_bars: int = 0


@dataclass
class PositionState:
    direction: str
    entry_datetime: datetime
    entry_price: float
    entry_bar_index: int
    entry_reason: str
    daily_direction: str
    stop_loss_price: float
    take_profit_price: float
    trade_params: TradeParams


@dataclass(frozen=True)
class StrategyTrade:
    trade_id: str
    strategy_code: str
    strategy_version: str
    symbol: str
    exchange: str
    direction: str
    entry_interval: str
    daily_direction: str
    entry_reason: str
    exit_reason: str
    entry_datetime: str
    exit_datetime: str
    entry_price: float
    exit_price: float
    stop_loss_price: float
    take_profit_price: float
    holding_bars: int
    volume: int
    contract_multiplier: int
    price_tick: float
    commission: float
    slippage: float
    gross_pnl: float
    net_pnl: float
    margin_required: float
    margin_rate: float
    gap_execution: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class SuBingJmV1bShortHoldStrategy(CtaTemplate):
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
        "take_profit_price",
        "entry_price",
        "last_signal",
        "signal_reason",
        "pending_action",
        "position_direction",
    ]

    def __init__(self, cta_engine: Any, strategy_name: str, vt_symbol: str, setting: dict[str, Any]) -> None:
        super().__init__(cta_engine, strategy_name, vt_symbol, setting)
        strategy_setting = {key: value for key, value in setting.items() if not key.startswith("_guiyi_")}
        self._explicit_none_trade_params = {
            key for key in ("price_tick", "contract_multiplier", "commission_rate", "commission_per_contract", "margin_rate")
            if key in strategy_setting and strategy_setting[key] is None
        }
        self._params: SuBingJmV1bShortHoldParams = validate_params(strategy_setting)
        for name, value in self._params.to_dict().items():
            setattr(self, name, value)

        self._bars: list[Any] = []
        self._daily_bars: list[Any] = _extract_daily_bars(setting)
        self._daily_snapshot_cache: dict[date, DailyDirectionSnapshot] = {}
        self._pending_order: PendingOrder | None = None
        self._position_state: PositionState | None = None
        self._entries_by_day: dict[tuple[date, str], int] = {}
        self.strategy_trades: list[dict[str, Any]] = []
        self.execution_events: list[dict[str, Any]] = []
        self.rejected_signals: list[dict[str, Any]] = []

        self.daily_direction = "unavailable"
        self.daily_direction_trading_day = ""
        self.daily_direction_reason = "not_started"
        self.entry_interval = self._params.entry_interval
        self.entry_reason = ""
        self.exit_reason = ""
        self.hold_bars = 0
        self.stop_loss_price = 0.0
        self.take_profit_price = 0.0
        self.entry_price = 0.0
        self.last_signal = "none"
        self.signal_reason = "not_started"
        self.pending_action = ""
        self.position_direction = "flat"

    def on_init(self) -> None:
        self.write_log("Su Bing JM V1-B short hold strategy initialized")

    def on_start(self) -> None:
        self.write_log("Su Bing JM V1-B short hold strategy started")

    def on_stop(self) -> None:
        self.write_log("Su Bing JM V1-B short hold strategy stopped")

    def on_bar(self, bar: Any) -> None:
        bar_index = len(self._bars)
        closed_this_bar = self._execute_pending_order(bar, bar_index)
        if not closed_this_bar and self._position_state is not None:
            closed_this_bar = self._manage_open_position(bar, bar_index)

        self._bars.append(bar)
        if not closed_this_bar and self._position_state is None and self._pending_order is None:
            self._schedule_entry_if_available(bar, len(self._bars) - 1)
        self.put_event()

    def _execute_pending_order(self, bar: Any, bar_index: int) -> bool:
        order = self._pending_order
        if order is None:
            self.pending_action = ""
            return False

        self._pending_order = None
        self.pending_action = ""
        fill_time = _bar_datetime(bar)
        open_price = _bar_float(bar, "open_price", "open")
        slippage = order.trade_params.price_tick * self._params.slippage_ticks

        if order.action in {"open_long", "open_short"}:
            if order.direction == "long":
                entry_price = open_price + slippage
                risk_distance = entry_price - order.stop_loss_price
                take_profit_price = entry_price + risk_distance * self._params.take_profit_r_multiple
            else:
                entry_price = open_price - slippage
                risk_distance = order.stop_loss_price - entry_price
                take_profit_price = entry_price - risk_distance * self._params.take_profit_r_multiple

            if risk_distance <= 0:
                self._reject_from_order(order, bar, "initial_risk_invalid_after_fill")
                return False
            if risk_distance > self._params.max_initial_stop_distance_ticks * order.trade_params.price_tick:
                self._reject_from_order(order, bar, "initial_stop_distance_too_wide")
                return False
            volume = self._position_size(entry_price, order.stop_loss_price, order.trade_params)
            if volume <= 0:
                self._reject_from_order(order, bar, "position_size_zero")
                return False

            self._position_state = PositionState(
                direction=order.direction,
                entry_datetime=fill_time,
                entry_price=entry_price,
                entry_bar_index=bar_index,
                entry_reason=order.reason,
                daily_direction=order.daily_direction,
                stop_loss_price=order.stop_loss_price,
                take_profit_price=take_profit_price,
                trade_params=order.trade_params,
            )
            self.position_direction = order.direction
            self.entry_price = entry_price
            self.entry_reason = order.reason
            self.stop_loss_price = order.stop_loss_price
            self.take_profit_price = take_profit_price
            self.last_signal = order.direction
            self.signal_reason = f"filled_next_bar_open|{order.reason}"
            self._record_entry(order, fill_time, entry_price)
            return False

        if order.action == "close" and self._position_state is not None:
            exit_price = _slipped_open_exit_price(open_price, self._position_state.direction, order.trade_params, self._params)
            self._close_position(
                bar,
                exit_price=exit_price,
                exit_reason=order.reason,
                holding_bars=order.holding_bars,
                gap_execution=False,
            )
            return True
        return False

    def _manage_open_position(self, bar: Any, bar_index: int) -> bool:
        position = self._position_state
        if position is None:
            return False
        self.hold_bars = bar_index - position.entry_bar_index + 1
        self.stop_loss_price = position.stop_loss_price
        self.take_profit_price = position.take_profit_price

        stop_hit = _bar_hits_stop(bar, position)
        take_profit_hit = _bar_hits_take_profit(bar, position)
        if stop_hit:
            exit_price, gap_execution = _level_exit_price(
                bar,
                position.direction,
                position.stop_loss_price,
                position.trade_params,
                self._params,
                reason="stop_loss",
            )
            self._close_position(
                bar,
                exit_price=exit_price,
                exit_reason="stop_loss",
                holding_bars=self.hold_bars,
                gap_execution=gap_execution,
            )
            return True

        if take_profit_hit:
            exit_price, gap_execution = _level_exit_price(
                bar,
                position.direction,
                position.take_profit_price,
                position.trade_params,
                self._params,
                reason="take_profit",
            )
            self._close_position(
                bar,
                exit_price=exit_price,
                exit_reason="take_profit",
                holding_bars=self.hold_bars,
                gap_execution=gap_execution,
            )
            return True

        if self._signal_failure_exit_required(bar, position):
            self._schedule_close(bar, "signal_failure_exit")
            return False

        if self.hold_bars >= self._params.planned_time_exit_bars and self._pending_order is None:
            self._schedule_close(bar, "time_exit_bar_8")
            return False
        return False

    def _schedule_entry_if_available(self, bar: Any, bar_index: int) -> None:
        min_bars = max(self._params.ema_period + 1, self._params.pullback_lookback_bars)
        if len(self._bars) < min_bars:
            self.last_signal = "none"
            self.signal_reason = "warming_up"
            return

        daily = self._confirmed_daily_snapshot_for_bar(bar)
        self._set_daily_direction(daily)
        trade_params, missing_reason = self._resolve_trade_params(bar)
        if missing_reason is not None:
            self._reject_signal(bar, missing_reason, daily)
            return
        if daily.direction not in {"long", "short"}:
            self._reject_signal(bar, f"daily_direction_blocks_entry|{daily.reason}", daily)
            return
        if self._daily_entry_count(_bar_trading_day(bar)) >= self._params.max_entries_per_trading_day_per_interval:
            self._reject_signal(bar, "daily_entry_limit_reached", daily)
            return

        decision = decide_entry(self._bars, daily, self._params, trade_params)
        if decision.direction == "none":
            self._reject_signal(bar, decision.rejected_reason or decision.entry_reason, daily)
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
            trade_params=trade_params,
        )
        self._increment_daily_entry_count(_bar_trading_day(bar))
        self.pending_action = action
        self.last_signal = decision.direction
        self.signal_reason = f"signal_on_close_pending_next_bar_open|{decision.entry_reason}"
        self.entry_reason = decision.entry_reason
        self.stop_loss_price = decision.stop_loss_price

    def _schedule_close(self, bar: Any, reason: str) -> None:
        position = self._position_state
        if position is None:
            return
        self._pending_order = PendingOrder(
            action="close",
            direction=position.direction,
            signal_datetime=_bar_datetime(bar),
            signal_bar_index=len(self._bars),
            reason=reason,
            daily_direction=position.daily_direction,
            stop_loss_price=position.stop_loss_price,
            trade_params=position.trade_params,
            holding_bars=self.hold_bars,
        )
        self.pending_action = "close"
        self.exit_reason = reason
        self.signal_reason = f"exit_on_close_pending_next_bar_open|{reason}"

    def _close_position(
        self,
        bar: Any,
        *,
        exit_price: float,
        exit_reason: str,
        holding_bars: int,
        gap_execution: bool,
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
        trade = StrategyTrade(
            trade_id=f"SB-JM-{len(self.strategy_trades) + 1}",
            strategy_code=self._params.strategy_code,
            strategy_version=self._params.strategy_version,
            symbol=trade_params.symbol,
            exchange=trade_params.exchange,
            direction=position.direction,
            entry_interval=self._params.entry_interval,
            daily_direction=position.daily_direction,
            entry_reason=position.entry_reason,
            exit_reason=exit_reason,
            entry_datetime=position.entry_datetime.isoformat(),
            exit_datetime=exit_time.isoformat(),
            entry_price=position.entry_price,
            exit_price=exit_price,
            stop_loss_price=position.stop_loss_price,
            take_profit_price=position.take_profit_price,
            holding_bars=holding_bars,
            volume=volume,
            contract_multiplier=trade_params.contract_multiplier,
            price_tick=trade_params.price_tick,
            commission=commission,
            slippage=slippage,
            gross_pnl=gross_pnl,
            net_pnl=net_pnl,
            margin_required=margin_required,
            margin_rate=trade_params.margin_rate,
            gap_execution=gap_execution,
        )
        self.strategy_trades.append(trade.to_dict())
        self.execution_events.append(
            {
                "action": "close",
                "exit_reason": exit_reason,
                "exit_datetime": exit_time.isoformat(),
                "exit_price": exit_price,
                "holding_bars": holding_bars,
                "entry_interval": self._params.entry_interval,
                "gap_execution": gap_execution,
            }
        )
        self.exit_reason = exit_reason
        self.hold_bars = holding_bars
        self.last_signal = "flat"
        self.signal_reason = f"position_closed|{exit_reason}"
        self.position_direction = "flat"
        self._position_state = None

    def _record_entry(self, order: PendingOrder, fill_time: datetime, entry_price: float) -> None:
        self.execution_events.append(
            {
                "action": order.action,
                "signal_datetime": order.signal_datetime.isoformat(),
                "fill_datetime": fill_time.isoformat(),
                "fill_price": entry_price,
                "entry_interval": self._params.entry_interval,
                "entry_reason": order.reason,
                "daily_direction": order.daily_direction,
                "stop_loss_price": order.stop_loss_price,
                "price_tick": order.trade_params.price_tick,
                "contract_multiplier": order.trade_params.contract_multiplier,
                "margin_rate": order.trade_params.margin_rate,
            }
        )

    def _reject_from_order(self, order: PendingOrder, bar: Any, reason: str) -> None:
        self.last_signal = "none"
        self.signal_reason = reason
        self.rejected_signals.append(
            {
                "rejected_reason": reason,
                "bar_datetime": _bar_datetime(bar).isoformat(),
                "signal_datetime": order.signal_datetime.isoformat(),
                "entry_interval": self._params.entry_interval,
                "daily_direction_state": order.daily_direction,
                "decision_status": "rejected_by_guardrail",
                "rule_source": "v0.1.1_execution_guardrail",
            }
        )

    def _reject_signal(self, bar: Any, reason: str, daily: DailyDirectionSnapshot) -> None:
        self.last_signal = "none"
        self.signal_reason = reason
        self.pending_action = ""
        self.rejected_signals.append(
            {
                "rejected_reason": reason,
                "rule_source": "v0.1.1_guardrail",
                "bar_datetime": _bar_datetime(bar).isoformat(),
                "entry_interval": self._params.entry_interval,
                "daily_direction_state": daily.direction,
                "decision_status": "rejected_by_guardrail",
            }
        )

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

    def _daily_entry_count(self, trading_day: date) -> int:
        return self._entries_by_day.get((trading_day, self._params.entry_interval), 0)

    def _increment_daily_entry_count(self, trading_day: date) -> None:
        key = (trading_day, self._params.entry_interval)
        self._entries_by_day[key] = self._entries_by_day.get(key, 0) + 1

    def _position_size(self, entry_price: float, stop_loss_price: float, trade_params: TradeParams) -> int:
        price_risk = abs(entry_price - stop_loss_price) * trade_params.contract_multiplier
        estimated_commission = _commission(entry_price, entry_price, 1, trade_params)
        estimated_slippage = trade_params.price_tick * self._params.slippage_ticks * trade_params.contract_multiplier * 2
        initial_risk = price_risk + estimated_commission + estimated_slippage
        if initial_risk <= 0:
            return 0
        raw_size = int((self._params.initial_capital * self._params.risk_per_trade_ratio) // initial_risk)
        size = min(raw_size, self._params.maximum_position)
        margin_required = entry_price * trade_params.contract_multiplier * size * trade_params.margin_rate
        if size <= 0 or margin_required > self._params.initial_capital:
            return 0
        return size

    def _signal_failure_exit_required(self, bar: Any, position: PositionState) -> bool:
        bars = [*self._bars, bar]
        if len(bars) < self._params.ema_period:
            return False
        indicator = calculate_entry_indicator(bars, self._params)
        close = _bar_float(bar, "close_price", "close")
        if position.direction == "long" and close < indicator.ema:
            return True
        if position.direction == "short" and close > indicator.ema:
            return True
        daily = self._confirmed_daily_snapshot_for_bar(bar)
        if position.direction == "long" and daily.direction != "long":
            return True
        if position.direction == "short" and daily.direction != "short":
            return True
        return False


def calculate_entry_indicator(bars: Sequence[Any], params: SuBingJmV1bShortHoldParams) -> IndicatorSnapshot:
    closes = [_bar_float(bar, "close_price", "close") for bar in bars]
    ema_values = _ema_series(closes, params.ema_period)
    return IndicatorSnapshot(ema=ema_values[-1], previous_ema=ema_values[-2], close=closes[-1])


def decide_entry(
    bars: Sequence[Any],
    daily: DailyDirectionSnapshot,
    params: SuBingJmV1bShortHoldParams,
    trade_params: TradeParams,
) -> EntryDecision:
    if len(bars) < max(params.ema_period + 1, params.pullback_lookback_bars):
        return EntryDecision("none", "warming_up", daily.direction, 0.0, rejected_reason="warming_up")

    indicator = calculate_entry_indicator(bars, params)
    current = bars[-1]
    current_close = _bar_float(current, "close_price", "close")
    current_low = _bar_float(current, "low_price", "low")
    current_high = _bar_float(current, "high_price", "high")
    tick = trade_params.price_tick
    max_distance = params.max_entry_ema_distance_ticks * tick
    recent_bars = bars[-params.pullback_lookback_bars :]
    recent_closes = [_bar_float(bar, "close_price", "close") for bar in bars]
    recent_ema_values = _ema_series(recent_closes, params.ema_period)[-params.pullback_lookback_bars :]

    if params.allow_long and daily.direction == "long":
        interacted = any(
            _bar_float(bar, "low_price", "low") <= ema + params.pullback_interaction_ticks * tick
            for bar, ema in zip(recent_bars, recent_ema_values, strict=True)
        )
        if not interacted:
            return EntryDecision("none", "long_pullback_not_interacted_with_ema21", daily.direction, 0.0)
        if current_close <= indicator.ema:
            return EntryDecision("none", "long_close_not_back_above_ema21", daily.direction, 0.0)
        if indicator.ema < indicator.previous_ema:
            return EntryDecision("none", "long_entry_ema21_not_rising", daily.direction, 0.0)
        if current_close - indicator.ema > max_distance:
            return EntryDecision("none", "long_entry_ema_distance_too_wide", daily.direction, 0.0)
        stop_loss = current_low - params.stop_buffer_ticks * tick
        return EntryDecision(
            "long",
            "daily_long_ema21_pullback_distance_guard",
            daily.direction,
            stop_loss,
            trade_params=trade_params,
        )

    if params.allow_short and daily.direction == "short":
        interacted = any(
            _bar_float(bar, "high_price", "high") >= ema - params.pullback_interaction_ticks * tick
            for bar, ema in zip(recent_bars, recent_ema_values, strict=True)
        )
        if not interacted:
            return EntryDecision("none", "short_pullback_not_interacted_with_ema21", daily.direction, 0.0)
        if current_close >= indicator.ema:
            return EntryDecision("none", "short_close_not_back_below_ema21", daily.direction, 0.0)
        if indicator.ema > indicator.previous_ema:
            return EntryDecision("none", "short_entry_ema21_not_falling", daily.direction, 0.0)
        if indicator.ema - current_close > max_distance:
            return EntryDecision("none", "short_entry_ema_distance_too_wide", daily.direction, 0.0)
        stop_loss = current_high + params.stop_buffer_ticks * tick
        return EntryDecision(
            "short",
            "daily_short_ema21_pullback_distance_guard",
            daily.direction,
            stop_loss,
            trade_params=trade_params,
        )

    return EntryDecision("none", f"{daily.direction}_entry_conditions_not_met", daily.direction, 0.0)


def confirmed_daily_direction_snapshot(
    *,
    current_bar: Any,
    daily_bars: Sequence[Any],
    params: SuBingJmV1bShortHoldParams,
) -> DailyDirectionSnapshot:
    current_trading_day = _bar_trading_day(current_bar)
    confirmed = [bar for bar in daily_bars if _bar_trading_day(bar) < current_trading_day]
    if len(confirmed) < params.daily_ema_period + 1:
        return DailyDirectionSnapshot(
            "unavailable",
            None,
            None,
            None,
            None,
            "daily_direction_unavailable_confirmed_bars_insufficient",
        )

    closes = [_bar_float(bar, "close_price", "close") for bar in confirmed]
    ema_values = _ema_series(closes, params.daily_ema_period)
    latest = confirmed[-1]
    latest_close = closes[-1]
    latest_ema = ema_values[-1]
    previous_ema = ema_values[-2]
    if latest_close > latest_ema and latest_ema >= previous_ema:
        return DailyDirectionSnapshot(
            "long",
            _bar_trading_day(latest),
            latest_close,
            latest_ema,
            previous_ema,
            "confirmed_daily_long_ema21",
        )
    if latest_close < latest_ema and latest_ema <= previous_ema:
        return DailyDirectionSnapshot(
            "short",
            _bar_trading_day(latest),
            latest_close,
            latest_ema,
            previous_ema,
            "confirmed_daily_short_ema21",
        )
    return DailyDirectionSnapshot(
        "neutral",
        _bar_trading_day(latest),
        latest_close,
        latest_ema,
        previous_ema,
        "daily_direction_neutral",
    )


def _bar_hits_stop(bar: Any, position: PositionState) -> bool:
    if position.direction == "long":
        return _bar_float(bar, "low_price", "low") <= position.stop_loss_price
    return _bar_float(bar, "high_price", "high") >= position.stop_loss_price


def _bar_hits_take_profit(bar: Any, position: PositionState) -> bool:
    if position.direction == "long":
        return _bar_float(bar, "high_price", "high") >= position.take_profit_price
    return _bar_float(bar, "low_price", "low") <= position.take_profit_price


def _level_exit_price(
    bar: Any,
    direction: str,
    level: float,
    trade_params: TradeParams,
    params: SuBingJmV1bShortHoldParams,
    *,
    reason: str,
) -> tuple[float, bool]:
    open_price = _bar_float(bar, "open_price", "open")
    slippage = trade_params.price_tick * params.slippage_ticks
    if direction == "long":
        if reason == "stop_loss" and open_price <= level:
            return open_price - slippage, True
        if reason == "take_profit" and open_price >= level:
            return open_price - slippage, True
        return level - slippage, False
    if reason == "stop_loss" and open_price >= level:
        return open_price + slippage, True
    if reason == "take_profit" and open_price <= level:
        return open_price + slippage, True
    return level + slippage, False


def _slipped_open_exit_price(
    open_price: float,
    direction: str,
    trade_params: TradeParams,
    params: SuBingJmV1bShortHoldParams,
) -> float:
    slippage = trade_params.price_tick * params.slippage_ticks
    if direction == "long":
        return open_price - slippage
    return open_price + slippage


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


SuBingJmV1bShortHold = SuBingJmV1bShortHoldStrategy
