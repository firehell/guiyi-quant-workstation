from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from math import floor, isfinite
from typing import Any, Literal, Mapping

from app.strategy.su_bing_ema21 import SignalSnapshot, SuBingParams, generate_signals


Direction = Literal["long", "short"]
OrderAction = Literal["open", "add", "reduce", "exit"]
OrderStatus = Literal["pending", "filled", "rejected", "cancelled"]
FeeType = Literal["rate", "fixed"]


@dataclass(frozen=True)
class BacktestBar:
    symbol: str
    contract: str
    exchange: str
    datetime: datetime
    trading_day: date
    open: float
    high: float
    low: float
    close: float
    volume: float
    open_interest: float | None = None
    period: str | None = None


@dataclass(frozen=True)
class ContractSpec:
    price_tick: float = 1.0
    volume_multiple: int = 10
    margin_rate: float = 0.10
    open_fee: float = 0.0001
    close_fee: float = 0.0001
    close_today_fee: float | None = None
    fee_type: FeeType = "rate"
    source: str = "fallback"


@dataclass(frozen=True)
class BacktestConfig:
    initial_capital: float = 100000.0
    risk_per_trade_pct: float = 0.01
    max_margin_usage_pct: float = 0.35
    slippage_ticks: int = 1
    take_profit_r: float = 2.0
    enable_take_profit: bool = True
    strategy_params: SuBingParams = field(default_factory=SuBingParams)


@dataclass
class BacktestOrder:
    order_id: str
    signal_time: datetime
    execution_time: datetime
    signal_index: int
    execution_index: int
    action: OrderAction
    direction: Direction
    requested_volume: int | None
    status: OrderStatus = "pending"
    reason: str = ""
    stop_price: float | None = None
    take_profit_price: float | None = None
    forced_price: float | None = None
    reject_reason: str | None = None


@dataclass(frozen=True)
class FillRecord:
    fill_id: str
    order_id: str
    time: datetime
    action: OrderAction
    direction: Direction
    volume: int
    price: float
    base_price: float
    commission: float
    slippage: float
    turnover: float
    margin: float
    reason: str
    stop_price: float | None = None
    take_profit_price: float | None = None


@dataclass(frozen=True)
class TradeRecord:
    trade_no: str
    instrument_symbol: str
    contract_code: str
    direction: Direction
    open_time: datetime
    open_price: float
    close_time: datetime
    close_price: float
    volume: int
    turnover: float
    commission: float
    slippage: float
    gross_pnl: float
    net_pnl: float
    return_pct: float
    holding_bars: int
    entry_reason: str
    exit_reason: str


@dataclass(frozen=True)
class EquityPoint:
    time: datetime
    equity: float
    cash: float
    floating_pnl: float
    margin_used: float
    position_volume: int
    close: float


@dataclass(frozen=True)
class DrawdownPoint:
    time: datetime
    equity: float
    peak_equity: float
    drawdown: float
    drawdown_pct: float


@dataclass
class Position:
    direction: Direction
    volume: int
    avg_price: float
    open_time: datetime
    open_index: int
    entry_reason: str
    entry_commission: float
    entry_slippage: float
    stop_price: float
    take_profit_price: float | None


@dataclass(frozen=True)
class BacktestReport:
    summary: dict[str, Any]
    trades: list[TradeRecord]
    orders: list[BacktestOrder]
    fills: list[FillRecord]
    equity_curve: list[EquityPoint]
    drawdown_curve: list[DrawdownPoint]
    warnings: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "summary": self.summary,
            "trades": [_json_ready(asdict(trade)) for trade in self.trades],
            "orders": [_json_ready(asdict(order)) for order in self.orders],
            "fills": [_json_ready(asdict(fill)) for fill in self.fills],
            "equity_curve": [_json_ready(asdict(point)) for point in self.equity_curve],
            "drawdown_curve": [_json_ready(asdict(point)) for point in self.drawdown_curve],
            "warnings": self.warnings,
        }


class BacktestEngine:
    def __init__(self, config: BacktestConfig | None = None, contract_spec: ContractSpec | None = None) -> None:
        self.config = config or BacktestConfig()
        self.contract_spec = contract_spec or ContractSpec()
        self.broker = BrokerSimulator(self.contract_spec, self.config.slippage_ticks)
        self.risk_manager = RiskManager(self.config, self.contract_spec)

    def run(
        self,
        bars: list[Mapping[str, Any] | BacktestBar],
        signals: list[SignalSnapshot] | None = None,
    ) -> BacktestReport:
        normalized_bars = [_coerce_bar(bar) for bar in bars]
        _validate_bars(normalized_bars)
        if len(normalized_bars) < 2:
            raise ValueError("at least two bars are required for next-bar execution")

        strategy_signals = signals or self._generate_incremental_signals(normalized_bars)
        if len(strategy_signals) != len(normalized_bars):
            raise ValueError("signals length must match bars length")

        portfolio = Portfolio(self.config.initial_capital, self.contract_spec)
        pending_orders: list[BacktestOrder] = []
        all_orders: list[BacktestOrder] = []
        fills: list[FillRecord] = []
        trades: list[TradeRecord] = []
        warnings: list[str] = []

        if normalized_bars[0].contract.endswith(".MAIN"):
            warnings.append("research_contract=true: 主力连续合约仅用于研究回测，不代表真实可交易合约")

        for index, bar in enumerate(normalized_bars):
            executable = [order for order in pending_orders if order.execution_index == index]
            pending_orders = [order for order in pending_orders if order.execution_index != index]
            for order in executable:
                fill, new_trades = self._execute_order(order, bar, index, portfolio)
                all_orders.append(order)
                if fill is not None:
                    fills.append(fill)
                trades.extend(new_trades)
                if order.status == "rejected" and order.reject_reason:
                    warnings.append(order.reject_reason)

            stop_order = self._make_stop_or_take_profit_order(portfolio, bar, index)
            if stop_order is not None:
                fill, new_trades = self._execute_order(stop_order, bar, index, portfolio, forced_price=stop_order.forced_price)
                all_orders.append(stop_order)
                if fill is not None:
                    fills.append(fill)
                trades.extend(new_trades)

            portfolio.record_equity(bar)

            if index < len(normalized_bars) - 1:
                order = self._signal_to_order(strategy_signals[index], normalized_bars, index, portfolio)
                if order is not None:
                    pending_orders.append(order)

        for order in pending_orders:
            order.status = "cancelled"
            order.reject_reason = "回测结束，无下一根K线可成交"
            all_orders.append(order)
            warnings.append(order.reject_reason)

        return ReportBuilder(self.config.initial_capital).build(
            trades=trades,
            orders=all_orders,
            fills=fills,
            equity_curve=portfolio.equity_curve,
            warnings=warnings,
            contract_spec=self.contract_spec,
        )

    def _generate_incremental_signals(self, bars: list[BacktestBar]) -> list[SignalSnapshot]:
        signals: list[SignalSnapshot] = []
        serializable_bars = [asdict(bar) for bar in bars]
        for end_index in range(1, len(serializable_bars) + 1):
            signals.append(generate_signals(serializable_bars[:end_index], params=self.config.strategy_params)[-1])
        return signals

    def _signal_to_order(
        self,
        signal: SignalSnapshot,
        bars: list[BacktestBar],
        index: int,
        portfolio: Portfolio,
    ) -> BacktestOrder | None:
        action = signal.trade_intent.get("action")
        if action not in {"trial_entry", "confirm_entry", "add_watch", "reduce", "exit"}:
            return None

        position = portfolio.position
        direction = signal.direction if signal.direction in {"long", "short"} else (position.direction if position else None)
        if direction is None:
            return None

        if action == "trial_entry":
            order_action: OrderAction = "open"
            requested_volume = self.risk_manager.target_open_volume(portfolio=portfolio, signal=signal, signal_bar=bars[index], fraction=0.5)
        elif action == "confirm_entry":
            if position is None or position.direction != direction or portfolio.floating_pnl(bars[index].close) <= 0:
                return None
            order_action = "add"
            target = self.risk_manager.target_open_volume(portfolio=portfolio, signal=signal, signal_bar=bars[index], fraction=1.0)
            requested_volume = max(0, target - position.volume)
        elif action == "add_watch":
            if position is None or position.direction != direction or portfolio.floating_pnl(bars[index].close) <= 0:
                return None
            order_action = "add"
            requested_volume = self.risk_manager.target_open_volume(portfolio=portfolio, signal=signal, signal_bar=bars[index], fraction=0.5)
        elif action == "reduce":
            if position is None:
                return None
            order_action = "reduce"
            requested_volume = max(1, position.volume // 2)
            direction = position.direction
        else:
            if position is None:
                return None
            order_action = "exit"
            requested_volume = position.volume
            direction = position.direction

        stop_price = None
        take_profit_price = None
        if order_action in {"open", "add"}:
            stop_price = stop_price_from_signal(signal=signal, signal_bar=bars[index], entry_price=bars[index].close, direction=direction)  # type: ignore[arg-type]
            if self.config.enable_take_profit:
                pseudo_fill = FillRecord(
                    fill_id="",
                    order_id="",
                    time=bars[index].datetime,
                    action=order_action,
                    direction=direction,  # type: ignore[arg-type]
                    volume=1,
                    price=bars[index].close,
                    base_price=bars[index].close,
                    commission=0,
                    slippage=0,
                    turnover=0,
                    margin=0,
                    reason="",
                )
                take_profit_price = take_profit_from_stop(pseudo_fill, stop_price, self.config.take_profit_r)

        return BacktestOrder(
            order_id=f"ORD-{index + 1:06d}",
            signal_time=bars[index].datetime,
            execution_time=bars[index + 1].datetime,
            signal_index=index,
            execution_index=index + 1,
            action=order_action,
            direction=direction,  # type: ignore[arg-type]
            requested_volume=requested_volume,
            reason="; ".join(signal.reasons),
            stop_price=stop_price,
            take_profit_price=take_profit_price,
        )

    def _make_stop_or_take_profit_order(
        self,
        portfolio: Portfolio,
        bar: BacktestBar,
        index: int,
    ) -> BacktestOrder | None:
        position = portfolio.position
        if position is None:
            return None

        trigger = self.broker.stop_or_take_profit_trigger(position, bar)
        if trigger is None:
            return None

        trigger_name, price = trigger
        return BacktestOrder(
            order_id=f"STP-{index + 1:06d}",
            signal_time=bar.datetime,
            execution_time=bar.datetime,
            signal_index=index,
            execution_index=index,
            action="exit",
            direction=position.direction,
            requested_volume=position.volume,
            reason=trigger_name,
            forced_price=price,
        )

    def _execute_order(
        self,
        order: BacktestOrder,
        bar: BacktestBar,
        index: int,
        portfolio: Portfolio,
        forced_price: float | None = None,
    ) -> tuple[FillRecord | None, list[TradeRecord]]:
        if order.requested_volume is None or order.requested_volume <= 0:
            order.status = "rejected"
            order.reject_reason = f"{order.order_id} 风险或保证金约束下无可成交手数"
            return None, []

        volume = min(order.requested_volume, portfolio.position.volume) if order.action in {"reduce", "exit"} and portfolio.position else order.requested_volume
        if volume <= 0:
            order.status = "rejected"
            order.reject_reason = f"{order.order_id} 当前无持仓可{order.action}"
            return None, []

        if order.action in {"open", "add"}:
            allowed_volume = self.risk_manager.affordable_volume(portfolio=portfolio, price=bar.open, desired_volume=volume)
            if allowed_volume <= 0:
                order.status = "rejected"
                order.reject_reason = f"{order.order_id} 保证金不足，跳过订单"
                return None, []
            volume = allowed_volume

        fill_price = self.broker.execution_price(order=order, bar=bar, forced_price=forced_price)
        base_price = self.broker.base_price(order=order, bar=bar, forced_price=forced_price)
        turnover = fill_price * volume * self.contract_spec.volume_multiple
        fee = self.broker.commission(action=order.action, turnover=turnover, volume=volume)
        slippage = abs(fill_price - base_price) * volume * self.contract_spec.volume_multiple
        margin = fill_price * volume * self.contract_spec.volume_multiple * self.contract_spec.margin_rate

        fill = FillRecord(
            fill_id=f"FILL-{len(portfolio.fills) + 1:06d}",
            order_id=order.order_id,
            time=bar.datetime,
            action=order.action,
            direction=order.direction,
            volume=volume,
            price=fill_price,
            base_price=base_price,
            commission=fee,
            slippage=slippage,
            turnover=turnover,
            margin=margin,
            reason=order.reason,
            stop_price=order.stop_price,
            take_profit_price=order.take_profit_price,
        )
        order.status = "filled"
        portfolio.fills.append(fill)
        trades = portfolio.apply_fill(fill=fill, bar=bar, bar_index=index)
        return fill, trades


class BrokerSimulator:
    def __init__(self, contract_spec: ContractSpec, slippage_ticks: int) -> None:
        self.contract_spec = contract_spec
        self.slippage_ticks = slippage_ticks

    def base_price(self, order: BacktestOrder, bar: BacktestBar, forced_price: float | None = None) -> float:
        if forced_price is not None and order.action == "exit":
            if order.direction == "long":
                if order.reason == "stop_loss" and bar.open <= forced_price:
                    return bar.open
                if order.reason == "take_profit" and bar.open >= forced_price:
                    return bar.open
                return forced_price
            if order.reason == "stop_loss" and bar.open >= forced_price:
                return bar.open
            if order.reason == "take_profit" and bar.open <= forced_price:
                return bar.open
            return forced_price
        return bar.open

    def execution_price(self, order: BacktestOrder, bar: BacktestBar, forced_price: float | None = None) -> float:
        base_price = self.base_price(order, bar, forced_price)
        tick_slippage = self.contract_spec.price_tick * self.slippage_ticks
        if self._is_buy(order):
            return base_price + tick_slippage
        return base_price - tick_slippage

    def commission(self, action: OrderAction, turnover: float, volume: int) -> float:
        fee_value = self.contract_spec.open_fee if action in {"open", "add"} else self.contract_spec.close_fee
        if action in {"reduce", "exit"} and self.contract_spec.close_today_fee is not None:
            fee_value = self.contract_spec.close_today_fee
        if self.contract_spec.fee_type == "fixed":
            return fee_value * volume
        return turnover * fee_value

    def stop_or_take_profit_trigger(self, position: Position, bar: BacktestBar) -> tuple[str, float] | None:
        if position.direction == "long":
            hit_stop = bar.open <= position.stop_price or bar.low <= position.stop_price
            hit_take_profit = position.take_profit_price is not None and (bar.open >= position.take_profit_price or bar.high >= position.take_profit_price)
            if hit_stop:
                return "stop_loss", position.stop_price
            if hit_take_profit:
                return "take_profit", position.take_profit_price
        else:
            hit_stop = bar.open >= position.stop_price or bar.high >= position.stop_price
            hit_take_profit = position.take_profit_price is not None and (bar.open <= position.take_profit_price or bar.low <= position.take_profit_price)
            if hit_stop:
                return "stop_loss", position.stop_price
            if hit_take_profit:
                return "take_profit", position.take_profit_price
        return None

    @staticmethod
    def _is_buy(order: BacktestOrder) -> bool:
        return (order.action in {"open", "add"} and order.direction == "long") or (order.action in {"reduce", "exit"} and order.direction == "short")


class RiskManager:
    def __init__(self, config: BacktestConfig, contract_spec: ContractSpec) -> None:
        self.config = config
        self.contract_spec = contract_spec

    def target_open_volume(
        self,
        portfolio: Portfolio,
        signal: SignalSnapshot,
        signal_bar: BacktestBar,
        fraction: float,
    ) -> int:
        direction = signal.direction
        if direction not in {"long", "short"}:
            return 0
        stop_price = stop_price_from_signal(signal=signal, signal_bar=signal_bar, entry_price=signal_bar.close, direction=direction)
        risk_per_lot = abs(signal_bar.close - stop_price) * self.contract_spec.volume_multiple
        if risk_per_lot <= 0:
            return 0
        risk_budget = portfolio.equity(signal_bar.close) * self.config.risk_per_trade_pct
        full_volume = floor(risk_budget / risk_per_lot)
        if full_volume <= 0:
            return 0
        return max(1, floor(full_volume * fraction))

    def affordable_volume(self, portfolio: Portfolio, price: float, desired_volume: int) -> int:
        equity = portfolio.equity(price)
        max_margin = equity * self.config.max_margin_usage_pct
        available_margin = max_margin - portfolio.margin_used(price)
        margin_per_lot = price * self.contract_spec.volume_multiple * self.contract_spec.margin_rate
        if margin_per_lot <= 0:
            return 0
        margin_volume = floor(available_margin / margin_per_lot)
        return min(desired_volume, max(0, margin_volume))


class Portfolio:
    def __init__(self, initial_capital: float, contract_spec: ContractSpec) -> None:
        self.initial_capital = initial_capital
        self.cash = initial_capital
        self.contract_spec = contract_spec
        self.position: Position | None = None
        self.fills: list[FillRecord] = []
        self.equity_curve: list[EquityPoint] = []
        self._trade_counter = 0

    def apply_fill(self, fill: FillRecord, bar: BacktestBar, bar_index: int) -> list[TradeRecord]:
        if fill.action in {"open", "add"}:
            self._apply_entry_fill(fill, bar, bar_index)
            return []
        return self._apply_exit_fill(fill, bar, bar_index)

    def _apply_entry_fill(self, fill: FillRecord, bar: BacktestBar, bar_index: int) -> None:
        self.cash -= fill.commission
        stop_price = _valid_entry_stop(fill, fill.stop_price, bar)
        take_profit_price = fill.take_profit_price
        if take_profit_price is not None and (
            (fill.direction == "long" and take_profit_price <= fill.price) or (fill.direction == "short" and take_profit_price >= fill.price)
        ):
            take_profit_price = take_profit_from_stop(fill, stop_price)
        if self.position is None:
            self.position = Position(
                direction=fill.direction,
                volume=fill.volume,
                avg_price=fill.price,
                open_time=fill.time,
                open_index=bar_index,
                entry_reason=fill.reason,
                entry_commission=fill.commission,
                entry_slippage=fill.slippage,
                stop_price=stop_price,
                take_profit_price=take_profit_price,
            )
            return
        if self.position.direction != fill.direction:
            raise ValueError("cannot add to opposite direction position")
        old_volume = self.position.volume
        new_volume = old_volume + fill.volume
        self.position.avg_price = (self.position.avg_price * old_volume + fill.price * fill.volume) / new_volume
        self.position.volume = new_volume
        self.position.entry_commission += fill.commission
        self.position.entry_slippage += fill.slippage
        if fill.direction == "long":
            self.position.stop_price = max(self.position.stop_price, stop_price)
        else:
            self.position.stop_price = min(self.position.stop_price, stop_price)
        if self.position.take_profit_price is not None or fill.take_profit_price is not None:
            self.position.take_profit_price = take_profit_from_stop(
                FillRecord(
                    **{
                        **asdict(fill),
                        "price": self.position.avg_price,
                    }
                ),
                self.position.stop_price,
            )

    def _apply_exit_fill(self, fill: FillRecord, bar: BacktestBar, bar_index: int) -> list[TradeRecord]:
        if self.position is None:
            return []
        close_volume = min(fill.volume, self.position.volume)
        volume_before = self.position.volume
        ratio = close_volume / volume_before
        gross_pnl = self._gross_pnl(fill.price, close_volume)
        entry_commission = self.position.entry_commission * ratio
        entry_slippage = self.position.entry_slippage * ratio
        commission = entry_commission + fill.commission
        slippage = entry_slippage + fill.slippage
        net_pnl = gross_pnl - commission
        self.cash += gross_pnl - fill.commission
        self._trade_counter += 1
        trade = TradeRecord(
            trade_no=f"TRD-{self._trade_counter:06d}",
            instrument_symbol=bar.symbol,
            contract_code=bar.contract,
            direction=self.position.direction,
            open_time=self.position.open_time,
            open_price=self.position.avg_price,
            close_time=fill.time,
            close_price=fill.price,
            volume=close_volume,
            turnover=(self.position.avg_price + fill.price) * close_volume * self.contract_spec.volume_multiple,
            commission=commission,
            slippage=slippage,
            gross_pnl=gross_pnl,
            net_pnl=net_pnl,
            return_pct=net_pnl / max(self.position.avg_price * close_volume * self.contract_spec.volume_multiple, 1e-9),
            holding_bars=bar_index - self.position.open_index,
            entry_reason=self.position.entry_reason,
            exit_reason=fill.reason,
        )
        self.position.entry_commission -= entry_commission
        self.position.entry_slippage -= entry_slippage
        self.position.volume -= close_volume
        if self.position.volume <= 0:
            self.position = None
        return [trade]

    def equity(self, close_price: float) -> float:
        return self.cash + self.floating_pnl(close_price)

    def floating_pnl(self, close_price: float) -> float:
        if self.position is None:
            return 0.0
        return self._gross_pnl(close_price, self.position.volume)

    def margin_used(self, close_price: float) -> float:
        if self.position is None:
            return 0.0
        return close_price * self.position.volume * self.contract_spec.volume_multiple * self.contract_spec.margin_rate

    def record_equity(self, bar: BacktestBar) -> None:
        self.equity_curve.append(
            EquityPoint(
                time=bar.datetime,
                equity=self.equity(bar.close),
                cash=self.cash,
                floating_pnl=self.floating_pnl(bar.close),
                margin_used=self.margin_used(bar.close),
                position_volume=0 if self.position is None else self.position.volume,
                close=bar.close,
            )
        )

    def _gross_pnl(self, exit_price: float, volume: int) -> float:
        if self.position is None:
            return 0.0
        multiplier = self.contract_spec.volume_multiple
        if self.position.direction == "long":
            return (exit_price - self.position.avg_price) * volume * multiplier
        return (self.position.avg_price - exit_price) * volume * multiplier


class ReportBuilder:
    def __init__(self, initial_capital: float) -> None:
        self.initial_capital = initial_capital

    def build(
        self,
        trades: list[TradeRecord],
        orders: list[BacktestOrder],
        fills: list[FillRecord],
        equity_curve: list[EquityPoint],
        warnings: list[str],
        contract_spec: ContractSpec,
    ) -> BacktestReport:
        drawdown_curve = self._drawdown_curve(equity_curve)
        summary = self._summary(trades, fills, equity_curve, drawdown_curve, orders, contract_spec)
        return BacktestReport(
            summary=summary,
            trades=trades,
            orders=orders,
            fills=fills,
            equity_curve=equity_curve,
            drawdown_curve=drawdown_curve,
            warnings=warnings,
        )

    def _summary(
        self,
        trades: list[TradeRecord],
        fills: list[FillRecord],
        equity_curve: list[EquityPoint],
        drawdown_curve: list[DrawdownPoint],
        orders: list[BacktestOrder],
        contract_spec: ContractSpec,
    ) -> dict[str, Any]:
        ending_equity = equity_curve[-1].equity if equity_curve else self.initial_capital
        total_return = (ending_equity / self.initial_capital - 1) if self.initial_capital else 0.0
        wins = [trade for trade in trades if trade.net_pnl > 0]
        losses = [trade for trade in trades if trade.net_pnl < 0]
        average_win = sum(trade.net_pnl for trade in wins) / len(wins) if wins else 0.0
        average_loss = abs(sum(trade.net_pnl for trade in losses) / len(losses)) if losses else 0.0
        profit_loss_ratio = average_win / average_loss if average_loss > 0 else 0.0
        max_drawdown = max((point.drawdown_pct for point in drawdown_curve), default=0.0)
        max_drawdown_amount = max((point.drawdown for point in drawdown_curve), default=0.0)
        return {
            "initial_capital": self.initial_capital,
            "ending_equity": ending_equity,
            "total_return": total_return,
            "annual_return": self._annual_return(equity_curve),
            "max_drawdown": max_drawdown,
            "max_drawdown_amount": max_drawdown_amount,
            "win_rate": len(wins) / len(trades) if trades else 0.0,
            "profit_loss_ratio": profit_loss_ratio,
            "expectancy": sum(trade.net_pnl for trade in trades) / len(trades) if trades else 0.0,
            "max_consecutive_losses": self._max_consecutive_losses(trades),
            "total_commission": sum(fill.commission for fill in fills),
            "total_slippage": sum(fill.slippage for fill in fills),
            "total_trades": len(trades),
            "total_orders": len(orders),
            "filled_orders": len([order for order in orders if order.status == "filled"]),
            "rejected_orders": len([order for order in orders if order.status == "rejected"]),
            "contract_spec": asdict(contract_spec),
        }

    def _drawdown_curve(self, equity_curve: list[EquityPoint]) -> list[DrawdownPoint]:
        peak = self.initial_capital
        points: list[DrawdownPoint] = []
        for point in equity_curve:
            peak = max(peak, point.equity)
            drawdown = peak - point.equity
            points.append(
                DrawdownPoint(
                    time=point.time,
                    equity=point.equity,
                    peak_equity=peak,
                    drawdown=drawdown,
                    drawdown_pct=drawdown / peak if peak else 0.0,
                )
            )
        return points

    def _annual_return(self, equity_curve: list[EquityPoint]) -> float:
        if len(equity_curve) < 2 or self.initial_capital <= 0:
            return 0.0
        elapsed_days = max((equity_curve[-1].time - equity_curve[0].time).total_seconds() / 86400, 1 / 24)
        total_return = equity_curve[-1].equity / self.initial_capital
        return total_return ** (365 / elapsed_days) - 1

    @staticmethod
    def _max_consecutive_losses(trades: list[TradeRecord]) -> int:
        max_losses = 0
        current = 0
        for trade in trades:
            if trade.net_pnl < 0:
                current += 1
                max_losses = max(max_losses, current)
            else:
                current = 0
        return max_losses


def run_su_bing_backtest(
    bars: list[Mapping[str, Any] | BacktestBar],
    config: BacktestConfig | None = None,
    contract_spec: ContractSpec | None = None,
) -> BacktestReport:
    return BacktestEngine(config=config, contract_spec=contract_spec).run(bars)


def stop_price_from_signal(signal: SignalSnapshot, signal_bar: BacktestBar, entry_price: float, direction: Direction) -> float:
    atr = float(signal.features.get("atr") or 0)
    fallback_distance = max(atr * 2, 1.0)
    if direction == "long":
        stop_price = signal_bar.low
        return stop_price if stop_price < entry_price else entry_price - fallback_distance
    stop_price = signal_bar.high
    return stop_price if stop_price > entry_price else entry_price + fallback_distance


def stop_price_from_fill(fill: FillRecord, bar: BacktestBar) -> float:
    fallback_distance = max(abs(bar.high - bar.low), 1.0)
    if fill.direction == "long":
        return bar.low if bar.low < fill.price else fill.price - fallback_distance
    return bar.high if bar.high > fill.price else fill.price + fallback_distance


def _valid_entry_stop(fill: FillRecord, stop_price: float | None, bar: BacktestBar) -> float:
    fallback = stop_price_from_fill(fill, bar)
    if stop_price is None:
        return fallback
    if fill.direction == "long" and stop_price < fill.price:
        return stop_price
    if fill.direction == "short" and stop_price > fill.price:
        return stop_price
    return fallback


def take_profit_from_stop(fill: FillRecord, stop_price: float, take_profit_r: float = 2.0) -> float:
    risk = abs(fill.price - stop_price)
    if fill.direction == "long":
        return fill.price + risk * take_profit_r
    return fill.price - risk * take_profit_r


def _coerce_bar(row: Mapping[str, Any] | BacktestBar) -> BacktestBar:
    if isinstance(row, BacktestBar):
        return row
    timestamp = row.get("datetime") or row.get("time")
    if isinstance(timestamp, str):
        parsed_datetime = datetime.fromisoformat(timestamp.replace("Z", "+00:00")).replace(tzinfo=None)
    elif isinstance(timestamp, datetime):
        parsed_datetime = timestamp.replace(tzinfo=None)
    else:
        raise ValueError("bar datetime is required")

    trading_day = row.get("trading_day") or parsed_datetime.date()
    if isinstance(trading_day, str):
        parsed_trading_day = date.fromisoformat(trading_day)
    elif isinstance(trading_day, datetime):
        parsed_trading_day = trading_day.date()
    elif isinstance(trading_day, date):
        parsed_trading_day = trading_day
    else:
        raise ValueError("bar trading_day is invalid")

    open_interest = row.get("open_interest", row.get("openInterest"))
    return BacktestBar(
        symbol=str(row["symbol"]),
        contract=str(row["contract"]),
        exchange=str(row["exchange"]),
        datetime=parsed_datetime,
        trading_day=parsed_trading_day,
        open=_finite_float(row["open"], "open"),
        high=_finite_float(row["high"], "high"),
        low=_finite_float(row["low"], "low"),
        close=_finite_float(row["close"], "close"),
        volume=_finite_float(row["volume"], "volume"),
        open_interest=None if open_interest is None else _finite_float(open_interest, "open_interest"),
        period=None if row.get("period") is None else str(row["period"]),
    )


def _validate_bars(bars: list[BacktestBar]) -> None:
    for index, bar in enumerate(bars):
        if bar.high < max(bar.open, bar.close, bar.low):
            raise ValueError(f"bar {index} has invalid OHLC high")
        if bar.low > min(bar.open, bar.close, bar.high):
            raise ValueError(f"bar {index} has invalid OHLC low")
        if bar.volume < 0:
            raise ValueError(f"bar {index} has negative volume")
        if index > 0 and bar.datetime <= bars[index - 1].datetime:
            raise ValueError("bars must be strictly sorted by datetime")


def _finite_float(value: Any, field_name: str) -> float:
    numeric = float(value)
    if not isfinite(numeric):
        raise ValueError(f"bar {field_name} must be finite")
    return numeric


def _json_ready(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _json_ready(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_ready(item) for item in value]
    return value
