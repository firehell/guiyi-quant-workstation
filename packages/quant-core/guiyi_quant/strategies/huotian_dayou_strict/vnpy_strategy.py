from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, dataclass, replace
from datetime import date, datetime
from typing import Any

import numpy as np

from .config_schema import (
    CANDIDATE_POLICY,
    DEFAULT_PARAMS,
    EXECUTION_SCOPE,
    FILL_POLICY,
    HuoTianDaYouStrictParams,
    STRATEGY_CODE,
    STRATEGY_VERSION,
    validate_params,
)

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


STRATEGY_CLASS_PATH = "guiyi_quant.strategies.huotian_dayou_strict.vnpy_strategy.HuoTianDaYouStrictStrategy"

NUMERIC_FIELDS = ("zk1", "zd1", "zd2", "var23")
BOOLEAN_FIELDS = (
    "yellow_candle",
    "white_candle",
    "buy_observation",
    "sell_observation",
    "callback_buy",
    "xg_observation",
)


@dataclass(frozen=True)
class CandidateCostRule:
    fee_type: str
    open_fee: float
    close_fee: float
    close_today_fee: float | None
    parameter_source: str
    main_contract_map_id: int
    main_contract_data_version: str


@dataclass(frozen=True)
class TradeParams:
    price_tick: float
    contract_multiplier: int
    commission_rate: float | None
    commission_per_contract: float | None
    margin_rate: float
    symbol: str
    exchange: str
    contract: str
    trading_day: str | None = None
    cost_rule: CandidateCostRule | None = None


@dataclass(frozen=True)
class EntryDecision:
    direction: str
    entry_reason: str
    stop_loss_price: float
    strict_fields: dict[str, Any]
    rejected_reason: str | None = None


@dataclass(frozen=True)
class PendingOrder:
    action: str
    direction: str
    signal_datetime: datetime
    signal_bar_index: int
    reason: str
    trade_params: TradeParams
    stop_loss_price: float
    strict_fields: dict[str, Any]
    holding_bars: int = 0


@dataclass
class PositionState:
    direction: str
    entry_datetime: datetime
    entry_signal_datetime: datetime
    entry_price: float
    entry_bar_index: int
    entry_reason: str
    stop_loss_price: float
    take_profit_price: float
    trade_params: TradeParams
    strict_fields: dict[str, Any]
    volume: int


@dataclass(frozen=True)
class StrategyTrade:
    tradeid: str
    strategy_code: str
    strategy_version: str
    candidate_policy: str
    execution_scope: str
    symbol: str
    exchange: str
    contract: str
    research_contract: str
    direction: str
    timeframe: str
    entry_reason: str
    exit_reason: str
    entry_signal_time: str
    entry_signal_source: str
    exit_signal_time: str | None
    exit_signal_source: str | None
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
    margin_ratio: float
    gap_execution: bool
    lineage_status: str
    raw_payload: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class HuoTianDaYouStrictStrategy(CtaTemplate):
    author = "guiyi_quant"
    parameters = list(DEFAULT_PARAMS)
    variables = [
        "entry_interval",
        "last_signal",
        "signal_reason",
        "pending_action",
        "position_direction",
        "entry_reason",
        "exit_reason",
        "hold_bars",
        "stop_loss_price",
        "take_profit_price",
        "entry_price",
    ]

    def __init__(self, cta_engine: Any, strategy_name: str, vt_symbol: str, setting: dict[str, Any]) -> None:
        super().__init__(cta_engine, strategy_name, vt_symbol, setting)
        strategy_setting = {key: value for key, value in setting.items() if not key.startswith("_guiyi_")}
        self._explicit_none_trade_params = {
            key
            for key in ("price_tick", "contract_multiplier", "commission_rate", "commission_per_contract", "margin_rate")
            if key in strategy_setting and strategy_setting[key] is None
        }
        self._params: HuoTianDaYouStrictParams = validate_params(strategy_setting)
        for name, value in self._params.to_dict().items():
            setattr(self, name, value)

        self._bars: list[Any] = []
        self._precomputed_snapshots: Sequence[dict[str, Any]] | None = setting.get("_guiyi_strict_snapshots")
        self._pending_order: PendingOrder | None = None
        self._position_state: PositionState | None = None
        self._blocked_entry_bar_index: int | None = None
        self.strategy_trades: list[dict[str, Any]] = []
        self.execution_events: list[dict[str, Any]] = []
        self.rejected_signals: list[dict[str, Any]] = []

        self.entry_interval = self._params.entry_interval
        self.last_signal = "none"
        self.signal_reason = "not_started"
        self.pending_action = ""
        self.position_direction = "flat"
        self.entry_reason = ""
        self.exit_reason = ""
        self.hold_bars = 0
        self.stop_loss_price = 0.0
        self.take_profit_price = 0.0
        self.entry_price = 0.0

    def on_init(self) -> None:
        self.write_log("HTDY strict formal backtest candidate initialized")

    def on_start(self) -> None:
        self.write_log("HTDY strict formal backtest candidate started")

    def on_stop(self) -> None:
        self.write_log("HTDY strict formal backtest candidate stopped")

    def on_bar(self, bar: Any) -> None:
        bar_index = len(self._bars)
        closed_on_open = self._execute_pending_order(bar, bar_index)
        if not closed_on_open and self._position_state is not None:
            self._manage_open_position_intrabar(bar, bar_index)

        self._bars.append(bar)
        current_index = len(self._bars) - 1
        if self._position_state is not None:
            self._schedule_close_from_current_close_if_needed(bar, current_index)
        elif self._pending_order is None and self._blocked_entry_bar_index != current_index:
            self._schedule_entry_if_available(bar, current_index)
        self.put_event()

    def finalize_sample_end(self) -> None:
        if not self._bars or self._position_state is None:
            return
        final_bar = self._bars[-1]
        exit_params, missing_reason = self._resolve_trade_params(final_bar)
        if missing_reason is not None or exit_params is None:
            raise ValueError(f"sample-end exit missing canonical cost parameters: {missing_reason}")
        exit_price = _bar_float(final_bar, "close_price", "close")
        if self._position_state.direction == "long":
            exit_price -= exit_params.price_tick * self._params.slippage_ticks
        else:
            exit_price += exit_params.price_tick * self._params.slippage_ticks
        self._close_position(
            final_bar,
            exit_price=exit_price,
            exit_reason="sample_end_forced_exit",
            exit_signal_time=_bar_datetime(final_bar),
            exit_signal_source="sample_end",
            holding_bars=max(1, len(self._bars) - self._position_state.entry_bar_index),
            gap_execution=False,
        )

    def _execute_pending_order(self, bar: Any, bar_index: int) -> bool:
        order = self._pending_order
        if order is None:
            self.pending_action = ""
            return False

        self._pending_order = None
        self.pending_action = ""
        fill_time = _bar_datetime(bar)
        open_price = _bar_float(bar, "open_price", "open")

        if order.action in {"open_long", "open_short"}:
            fill_params, missing_reason = self._resolve_trade_params(bar)
            if missing_reason is not None or fill_params is None:
                self._reject_from_order(order, bar, missing_reason or "missing_fill_cost_parameters")
                return False
            order = replace(order, trade_params=fill_params)
            slippage_price = fill_params.price_tick * self._params.slippage_ticks
            entry_price = open_price + slippage_price if order.direction == "long" else open_price - slippage_price
            risk_distance = (
                entry_price - order.stop_loss_price
                if order.direction == "long"
                else order.stop_loss_price - entry_price
            )
            if risk_distance <= 0:
                self._reject_from_order(order, bar, "initial_risk_invalid_after_fill")
                return False
            take_profit_price = (
                entry_price + risk_distance * self._params.take_profit_r_multiple
                if order.direction == "long"
                else entry_price - risk_distance * self._params.take_profit_r_multiple
            )
            volume = self._position_size(entry_price, order.stop_loss_price, order.trade_params)
            if volume <= 0:
                self._reject_from_order(order, bar, "position_size_zero_or_margin_blocked")
                return False

            self._position_state = PositionState(
                direction=order.direction,
                entry_datetime=fill_time,
                entry_signal_datetime=order.signal_datetime,
                entry_price=entry_price,
                entry_bar_index=bar_index,
                entry_reason=order.reason,
                stop_loss_price=order.stop_loss_price,
                take_profit_price=take_profit_price,
                trade_params=order.trade_params,
                strict_fields=order.strict_fields,
                volume=volume,
            )
            self.position_direction = order.direction
            self.entry_price = entry_price
            self.entry_reason = order.reason
            self.stop_loss_price = order.stop_loss_price
            self.take_profit_price = take_profit_price
            self.last_signal = order.direction
            self.signal_reason = f"filled_next_bar_open|{order.reason}"
            self._record_entry(order, fill_time, entry_price, volume)
            return False

        if order.action == "close" and self._position_state is not None:
            exit_params, missing_reason = self._resolve_trade_params(bar)
            if missing_reason is not None or exit_params is None:
                raise ValueError(f"close fill missing canonical cost parameters: {missing_reason}")
            exit_price = _slipped_open_exit_price(open_price, self._position_state.direction, exit_params, self._params)
            self._close_position(
                bar,
                exit_price=exit_price,
                exit_reason=order.reason,
                exit_signal_time=order.signal_datetime,
                exit_signal_source="strategy_execution_event",
                holding_bars=order.holding_bars,
                gap_execution=False,
            )
            self._blocked_entry_bar_index = bar_index
            return True
        return False

    def _manage_open_position_intrabar(self, bar: Any, bar_index: int) -> None:
        position = self._position_state
        if position is None:
            return
        self.hold_bars = bar_index - position.entry_bar_index + 1
        exit_params, missing_reason = self._resolve_trade_params(bar)
        if missing_reason is not None or exit_params is None:
            raise ValueError(f"intrabar exit missing canonical cost parameters: {missing_reason}")
        stop_hit = _bar_hits_stop(bar, position)
        take_profit_hit = _bar_hits_take_profit(bar, position)
        if stop_hit:
            exit_price, gap_execution = _level_exit_price(
                bar,
                position.direction,
                position.stop_loss_price,
                exit_params,
                self._params,
            )
            self._close_position(
                bar,
                exit_price=exit_price,
                exit_reason="stop_loss",
                exit_signal_time=None,
                exit_signal_source="intrabar_stop",
                holding_bars=self.hold_bars,
                gap_execution=gap_execution,
            )
            self._blocked_entry_bar_index = bar_index
            return
        if take_profit_hit:
            exit_price, gap_execution = _level_exit_price(
                bar,
                position.direction,
                position.take_profit_price,
                exit_params,
                self._params,
            )
            self._close_position(
                bar,
                exit_price=exit_price,
                exit_reason="take_profit",
                exit_signal_time=None,
                exit_signal_source="intrabar_take_profit",
                holding_bars=self.hold_bars,
                gap_execution=gap_execution,
            )
            self._blocked_entry_bar_index = bar_index

    def _schedule_close_from_current_close_if_needed(self, bar: Any, current_index: int) -> None:
        position = self._position_state
        if position is None or self._pending_order is not None:
            return
        held_bars = current_index - position.entry_bar_index + 1
        self.hold_bars = held_bars
        snapshot = self._current_snapshot()
        reverse_signal = (
            position.direction == "long" and bool(snapshot["sell_observation"])
        ) or (
            position.direction == "short" and (bool(snapshot["buy_observation"]) or bool(snapshot["xg_observation"]))
        )
        if reverse_signal:
            self._schedule_close(bar, "reverse_observation_exit", held_bars, snapshot)
            return
        if held_bars >= self._params.planned_time_exit_bars:
            self._schedule_close(bar, "time_exit_bar_8", held_bars, snapshot)

    def _schedule_entry_if_available(self, bar: Any, bar_index: int) -> None:
        trade_params, missing_reason = self._resolve_trade_params(bar)
        snapshot = self._current_snapshot()
        if missing_reason is not None:
            if _has_any_candidate(snapshot):
                self._reject_signal(bar, missing_reason, snapshot)
            return
        assert trade_params is not None
        decision = decide_entry(self._bars, self._params, trade_params, snapshot=snapshot)
        if decision.direction == "none":
            if decision.rejected_reason:
                self._reject_signal(bar, decision.rejected_reason, decision.strict_fields)
            return

        action = "open_long" if decision.direction == "long" else "open_short"
        self._pending_order = PendingOrder(
            action=action,
            direction=decision.direction,
            signal_datetime=_bar_datetime(bar),
            signal_bar_index=bar_index,
            reason=decision.entry_reason,
            trade_params=trade_params,
            stop_loss_price=decision.stop_loss_price,
            strict_fields=decision.strict_fields,
        )
        self.pending_action = action
        self.last_signal = decision.direction
        self.signal_reason = f"signal_on_close_pending_next_bar_open|{decision.entry_reason}"
        self.entry_reason = decision.entry_reason
        self.stop_loss_price = decision.stop_loss_price

    def _schedule_close(self, bar: Any, reason: str, holding_bars: int, strict_fields: dict[str, Any]) -> None:
        position = self._position_state
        if position is None:
            return
        self._pending_order = PendingOrder(
            action="close",
            direction=position.direction,
            signal_datetime=_bar_datetime(bar),
            signal_bar_index=len(self._bars) - 1,
            reason=reason,
            trade_params=position.trade_params,
            stop_loss_price=position.stop_loss_price,
            strict_fields=strict_fields,
            holding_bars=holding_bars,
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
        exit_signal_time: datetime | None,
        exit_signal_source: str | None,
        holding_bars: int,
        gap_execution: bool,
    ) -> None:
        position = self._position_state
        if position is None:
            return
        trade_params = position.trade_params
        exit_params, missing_reason = self._resolve_trade_params(bar)
        if missing_reason is not None or exit_params is None:
            raise ValueError(f"trade close missing canonical cost parameters: {missing_reason}")
        exit_time = _bar_datetime(bar)
        volume = position.volume
        gross_pnl = _gross_pnl(position.direction, position.entry_price, exit_price, volume, trade_params.contract_multiplier)
        commission = commission_for_trade(position.entry_price, exit_price, volume, trade_params, exit_params)
        slippage = self._params.slippage_ticks * volume * (
            trade_params.price_tick * trade_params.contract_multiplier
            + exit_params.price_tick * exit_params.contract_multiplier
        )
        net_pnl = gross_pnl - commission - slippage
        margin_required = position.entry_price * trade_params.contract_multiplier * volume * trade_params.margin_rate
        trade_no = f"HTDY-{len(self.strategy_trades) + 1}"
        trade = StrategyTrade(
            tradeid=trade_no,
            strategy_code=STRATEGY_CODE,
            strategy_version=STRATEGY_VERSION,
            candidate_policy=CANDIDATE_POLICY,
            execution_scope=EXECUTION_SCOPE,
            symbol=_symbol_root(trade_params.symbol),
            exchange=trade_params.exchange,
            contract=trade_params.contract,
            research_contract=self.vt_symbol.rsplit(".", 1)[0],
            direction=position.direction,
            timeframe=self._params.entry_interval,
            entry_reason=position.entry_reason,
            exit_reason=exit_reason,
            entry_signal_time=position.entry_signal_datetime.isoformat(),
            entry_signal_source="strategy_execution_event",
            exit_signal_time=None if exit_signal_time is None else exit_signal_time.isoformat(),
            exit_signal_source=exit_signal_source,
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
            margin_ratio=trade_params.margin_rate,
            gap_execution=gap_execution,
            lineage_status="mapped",
            raw_payload={
                "candidate_policy": CANDIDATE_POLICY,
                "strict_entry_fields": position.strict_fields,
                "exit_reason": exit_reason,
                "gap_execution": gap_execution,
            },
        )
        trade_payload = trade.to_dict()
        trade_payload.update(
            {
                "entry_contract": trade_params.contract,
                "exit_contract": exit_params.contract,
                "entry_trading_day": trade_params.trading_day,
                "exit_trading_day": exit_params.trading_day,
                "fee_rule_source": {
                    "entry": None if trade_params.cost_rule is None else asdict(trade_params.cost_rule),
                    "exit": None if exit_params.cost_rule is None else asdict(exit_params.cost_rule),
                },
                "main_contract_source": {
                    "entry_map_id": None if trade_params.cost_rule is None else trade_params.cost_rule.main_contract_map_id,
                    "exit_map_id": None if exit_params.cost_rule is None else exit_params.cost_rule.main_contract_map_id,
                },
            }
        )
        self.strategy_trades.append(trade_payload)
        self.execution_events.append(
            {
                "action": "close",
                "trade_no": trade_no,
                "signal_datetime": None if exit_signal_time is None else exit_signal_time.isoformat(),
                "fill_datetime": exit_time.isoformat(),
                "exit_reason": exit_reason,
                "fill_price": exit_price,
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

    def _record_entry(self, order: PendingOrder, fill_time: datetime, entry_price: float, volume: int) -> None:
        self.execution_events.append(
            {
                "action": order.action,
                "signal_datetime": order.signal_datetime.isoformat(),
                "fill_datetime": fill_time.isoformat(),
                "fill_price": entry_price,
                "entry_interval": self._params.entry_interval,
                "entry_reason": order.reason,
                "stop_loss_price": order.stop_loss_price,
                "price_tick": order.trade_params.price_tick,
                "contract_multiplier": order.trade_params.contract_multiplier,
                "margin_rate": order.trade_params.margin_rate,
                "candidate_policy": CANDIDATE_POLICY,
                "volume": volume,
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
                "decision_status": "rejected_by_guardrail",
                "rule_source": STRATEGY_VERSION,
                "candidate_policy": CANDIDATE_POLICY,
            }
        )

    def _reject_signal(self, bar: Any, reason: str, strict_fields: dict[str, Any]) -> None:
        self.last_signal = "none"
        self.signal_reason = reason
        self.pending_action = ""
        self.rejected_signals.append(
            {
                "rejected_reason": reason,
                "rule_source": STRATEGY_VERSION,
                "bar_datetime": _bar_datetime(bar).isoformat(),
                "entry_interval": self._params.entry_interval,
                "decision_status": "rejected_by_guardrail",
                "candidate_policy": CANDIDATE_POLICY,
                "strict_fields": strict_fields,
            }
        )

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
        contract = str(_bar_value(bar, "contract") or _bar_value(bar, "contract_code") or symbol)
        trading_day_value = _bar_value(bar, "trading_day")
        trading_day = None if trading_day_value is None else _date_text(trading_day_value)
        fee_type = _bar_value(bar, "fee_type")
        open_fee = _first_optional_float(_bar_value(bar, "open_fee"))
        close_fee = _first_optional_float(_bar_value(bar, "close_fee"))
        close_today_fee = _first_optional_float(_bar_value(bar, "close_today_fee"))
        cost_rule = None
        if fee_type is not None or open_fee is not None or close_fee is not None:
            if fee_type not in {"rate", "fixed"} or open_fee is None or close_fee is None:
                return None, "missing_canonical_commission_rule"
            source = str(_bar_value(bar, "parameter_source") or "")
            map_id = _first_optional_int(_bar_value(bar, "main_contract_map_id"))
            map_version = str(_bar_value(bar, "main_contract_data_version") or "")
            if not source or map_id is None or not map_version or trading_day is None:
                return None, "missing_canonical_cost_lineage"
            cost_rule = CandidateCostRule(
                fee_type=str(fee_type),
                open_fee=float(open_fee),
                close_fee=float(close_fee),
                close_today_fee=None if close_today_fee is None else float(close_today_fee),
                parameter_source=source,
                main_contract_map_id=map_id,
                main_contract_data_version=map_version,
            )
        return (
            TradeParams(
                price_tick=float(price_tick),
                contract_multiplier=int(multiplier),
                commission_rate=None if commission_rate is None else float(commission_rate),
                commission_per_contract=None if commission_per_contract is None else float(commission_per_contract),
                margin_rate=float(margin_rate),
                symbol=symbol,
                exchange=exchange,
                contract=contract,
                trading_day=trading_day,
                cost_rule=cost_rule,
            ),
            None,
        )

    def _current_snapshot(self) -> dict[str, Any]:
        if self._precomputed_snapshots is None:
            return strict_signal_snapshot(self._bars, self._params)
        index = len(self._bars) - 1
        if index < 0 or index >= len(self._precomputed_snapshots):
            raise ValueError("precomputed HTDY strict snapshot index is out of range")
        return dict(self._precomputed_snapshots[index])

    def _position_size(self, entry_price: float, stop_loss_price: float, trade_params: TradeParams) -> int:
        price_risk = abs(entry_price - stop_loss_price) * trade_params.contract_multiplier
        estimated_commission = commission_for_trade(entry_price, entry_price, 1, trade_params, trade_params)
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


def decide_entry(
    bars: Sequence[Any],
    params: HuoTianDaYouStrictParams,
    trade_params: TradeParams,
    *,
    snapshot: dict[str, Any] | None = None,
) -> EntryDecision:
    snapshot = snapshot or strict_signal_snapshot(bars, params)
    long_candidate = bool(snapshot["buy_observation"]) or bool(snapshot["xg_observation"])
    short_candidate = bool(snapshot["sell_observation"])
    if long_candidate and short_candidate:
        return EntryDecision("none", "conflict_candidate_skipped", 0.0, snapshot, "conflict_candidate_skipped")
    current = bars[-1]
    if long_candidate and params.allow_long:
        stop_loss = _bar_float(current, "low_price", "low") - params.stop_buffer_ticks * trade_params.price_tick
        return EntryDecision("long", "htdy_strict_long_observation", stop_loss, snapshot)
    if short_candidate and params.allow_short:
        stop_loss = _bar_float(current, "high_price", "high") + params.stop_buffer_ticks * trade_params.price_tick
        return EntryDecision("short", "htdy_strict_short_observation", stop_loss, snapshot)
    return EntryDecision("none", "no_strict_candidate", 0.0, snapshot, None)


def strict_signal_snapshot(bars: Sequence[Any], params: HuoTianDaYouStrictParams) -> dict[str, Any]:
    if not bars:
        return {name: None for name in NUMERIC_FIELDS} | {name: False for name in BOOLEAN_FIELDS}
    fields = compute_strict_fields(
        [_bar_float(bar, "open_price", "open") for bar in bars],
        [_bar_float(bar, "high_price", "high") for bar in bars],
        [_bar_float(bar, "low_price", "low") for bar in bars],
        [_bar_float(bar, "close_price", "close") for bar in bars],
        channel_period=params.channel_period,
        var23_period=params.var23_period,
    )
    index = len(bars) - 1
    return {name: _scalar_or_none(fields[name][index]) for name in (*NUMERIC_FIELDS, *BOOLEAN_FIELDS)}


def build_strict_snapshot_series(
    bars: Sequence[Any],
    params: HuoTianDaYouStrictParams,
) -> list[dict[str, Any]]:
    if not bars:
        return []
    fields = compute_strict_fields(
        [_bar_float(bar, "open_price", "open") for bar in bars],
        [_bar_float(bar, "high_price", "high") for bar in bars],
        [_bar_float(bar, "low_price", "low") for bar in bars],
        [_bar_float(bar, "close_price", "close") for bar in bars],
        channel_period=params.channel_period,
        var23_period=params.var23_period,
    )
    return [
        {name: _scalar_or_none(fields[name][index]) for name in (*NUMERIC_FIELDS, *BOOLEAN_FIELDS)}
        for index in range(len(bars))
    ]


def compute_strict_fields(
    open_: Sequence[float],
    high: Sequence[float],
    low: Sequence[float],
    close: Sequence[float],
    *,
    channel_period: int = 25,
    var23_period: int = 6,
) -> dict[str, np.ndarray]:
    _require_positive_period("channel_period", channel_period)
    _require_positive_period("var23_period", var23_period)
    o = np.asarray(open_, dtype=float)
    h = np.asarray(high, dtype=float)
    low_arr = np.asarray(low, dtype=float)
    c = np.asarray(close, dtype=float)
    _require_same_length(open=o, high=h, low=low_arr, close=c)

    ema_high = _double_trailing_ema(h, channel_period)
    ema_low = _double_trailing_ema(low_arr, channel_period)
    band_width = ema_high - ema_low
    zk1 = ema_high + band_width
    zd1 = ema_low - band_width
    zd2 = _trailing_ema_sma_seed(zd1, channel_period)
    body_high = np.maximum(o, c)
    body_low = np.minimum(o, c)
    over_low = np.maximum(body_low, zk1)
    yellow_candle = ((zd1 > low_arr) & (zd1 < h)) | ((zd1 > np.minimum(c, o)) & (zd1 < np.maximum(c, o))) | (zd1 > h)
    white_candle = (body_high > zk1) & (body_high > over_low)
    buy_observation = _new_third_consecutive(yellow_candle)
    sell_observation = _new_third_consecutive(white_candle)
    delta = c - _ref(c, 1)
    var23_num = _double_trailing_ema(delta, var23_period)
    var23_den = _double_trailing_ema(np.abs(delta), var23_period)
    with np.errstate(divide="ignore", invalid="ignore"):
        var23 = np.where(np.isfinite(var23_den) & (var23_den != 0), 100.0 * var23_num / var23_den, np.nan)
    callback_buy = (_llv(var23, 2) == _llv(var23, 7)) & (_count(var23 < 0, 2) > 0) & _cross(var23, _ma(var23, 2))
    xg_observation = (zd1 > h) & callback_buy & (low_arr <= zd1)
    return {
        "zk1": zk1,
        "zd1": zd1,
        "zd2": zd2,
        "yellow_candle": yellow_candle,
        "white_candle": white_candle,
        "buy_observation": buy_observation,
        "sell_observation": sell_observation,
        "var23": var23,
        "callback_buy": callback_buy,
        "xg_observation": xg_observation,
    }


def build_normalized_result(strategy: HuoTianDaYouStrictStrategy) -> dict[str, Any]:
    trades = list(strategy.strategy_trades)
    return {
        "summary": {
            "capital": strategy._params.initial_capital,
            "initial_capital": strategy._params.initial_capital,
            "strategy_code": STRATEGY_CODE,
            "strategy_version": STRATEGY_VERSION,
            "candidate_policy": CANDIDATE_POLICY,
            "execution_scope": EXECUTION_SCOPE,
            "fill_policy": FILL_POLICY,
            "quality_status": {"status": "passed"},
        },
        "trades": trades,
        "orders": _orders_from_trades(trades),
        "strategy_execution_events": list(strategy.execution_events),
        "warnings": [row["rejected_reason"] for row in strategy.rejected_signals],
        "metadata": {
            "engine_version": "htdy_formal_candidate_dry_run_v0",
            "candidate_policy": CANDIDATE_POLICY,
            "execution_scope": EXECUTION_SCOPE,
        },
    }


def _orders_from_trades(trades: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    orders: list[dict[str, Any]] = []
    for index, trade in enumerate(trades, start=1):
        trade_no = str(trade["tradeid"])
        orders.extend(
            [
                {
                    "orderid": f"{trade_no}-OPEN",
                    "trade_no": trade_no,
                    "leg": "entry",
                    "symbol": trade["symbol"],
                    "contract": trade["contract"],
                    "direction": trade["direction"],
                    "offset": "open",
                    "status": "all_traded",
                    "price": trade["entry_price"],
                    "volume": trade["volume"],
                    "traded": trade["volume"],
                    "datetime": trade["entry_datetime"],
                    "lineage_source": "strategy_execution_event",
                    "mapping_status": "mapped",
                    "sequence": index * 2 - 1,
                },
                {
                    "orderid": f"{trade_no}-CLOSE",
                    "trade_no": trade_no,
                    "leg": "exit",
                    "symbol": trade["symbol"],
                    "contract": trade["contract"],
                    "direction": "short" if trade["direction"] == "long" else "long",
                    "offset": "close",
                    "status": "all_traded",
                    "price": trade["exit_price"],
                    "volume": trade["volume"],
                    "traded": trade["volume"],
                    "datetime": trade["exit_datetime"],
                    "lineage_source": "strategy_execution_event",
                    "mapping_status": "mapped",
                    "sequence": index * 2,
                },
            ]
        )
    return orders


def _double_trailing_ema(values: Sequence[float], period: int) -> np.ndarray:
    return _trailing_ema_sma_seed(_trailing_ema_sma_seed(values, period), period)


def _trailing_ema_sma_seed(values: Sequence[float], period: int) -> np.ndarray:
    arr = np.asarray(values, dtype=float)
    out = np.full(len(arr), np.nan, dtype=float)
    alpha = 2.0 / (period + 1)
    previous: float | None = None
    for index, value in enumerate(arr):
        if previous is None:
            start = index - period + 1
            if start < 0:
                continue
            window = arr[start : index + 1]
            if not np.all(np.isfinite(window)):
                continue
            previous = float(np.mean(window))
            out[index] = previous
            continue
        if not np.isfinite(value):
            continue
        previous = alpha * float(value) + (1.0 - alpha) * previous
        out[index] = previous
    return out


def _ma(values: Sequence[float], period: int) -> np.ndarray:
    arr = np.asarray(values, dtype=float)
    out = np.full(len(arr), np.nan, dtype=float)
    for index in range(period - 1, len(arr)):
        window = arr[index - period + 1 : index + 1]
        if np.all(np.isfinite(window)):
            out[index] = float(np.mean(window))
    return out


def _ref(values: Sequence[float], periods: int = 1) -> np.ndarray:
    arr = np.asarray(values, dtype=float)
    out = np.full(len(arr), np.nan, dtype=float)
    out[periods:] = arr[:-periods]
    return out


def _llv(values: Sequence[float], period: int) -> np.ndarray:
    arr = np.asarray(values, dtype=float)
    out = np.full(len(arr), np.nan, dtype=float)
    for index in range(len(arr)):
        window = arr[max(0, index - period + 1) : index + 1]
        finite = window[np.isfinite(window)]
        if len(finite) > 0:
            out[index] = float(np.min(finite))
    return out


def _count(condition: Sequence[bool], period: int) -> np.ndarray:
    flags = np.asarray(condition, dtype=bool)
    out = np.zeros(len(flags), dtype=int)
    for index in range(len(flags)):
        out[index] = int(np.sum(flags[max(0, index - period + 1) : index + 1]))
    return out


def _cross(left: Sequence[float], right: Sequence[float]) -> np.ndarray:
    left_arr = np.asarray(left, dtype=float)
    right_arr = np.asarray(right, dtype=float)
    _require_same_length(left=left_arr, right=right_arr)
    out = np.zeros(len(left_arr), dtype=bool)
    for index in range(1, len(left_arr)):
        values = (left_arr[index - 1], right_arr[index - 1], left_arr[index], right_arr[index])
        if not all(np.isfinite(value) for value in values):
            continue
        out[index] = left_arr[index - 1] <= right_arr[index - 1] and left_arr[index] > right_arr[index]
    return out


def _new_third_consecutive(flags: Sequence[bool]) -> np.ndarray:
    arr = np.asarray(flags, dtype=bool)
    out = np.zeros(len(arr), dtype=bool)
    for index in range(2, len(arr)):
        previous_three = arr[index] and arr[index - 1] and arr[index - 2]
        out[index] = previous_three and not bool(arr[index - 3] if index >= 3 else False)
    return out


def _require_same_length(**arrays: Sequence[Any]) -> None:
    lengths = {name: len(value) for name, value in arrays.items()}
    if len(set(lengths.values())) != 1:
        raise ValueError(f"input lengths must match: {lengths}")


def _require_positive_period(name: str, value: int) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")


def _has_any_candidate(snapshot: dict[str, Any]) -> bool:
    return bool(snapshot["buy_observation"] or snapshot["xg_observation"] or snapshot["sell_observation"])


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
    level_price: float,
    trade_params: TradeParams,
    params: HuoTianDaYouStrictParams,
) -> tuple[float, bool]:
    open_price = _bar_float(bar, "open_price", "open")
    slippage_price = trade_params.price_tick * params.slippage_ticks
    if direction == "long":
        if open_price <= level_price:
            return open_price - slippage_price, True
        return level_price - slippage_price, False
    if open_price >= level_price:
        return open_price + slippage_price, True
    return level_price + slippage_price, False


def _slipped_open_exit_price(
    open_price: float,
    direction: str,
    trade_params: TradeParams,
    params: HuoTianDaYouStrictParams,
) -> float:
    slippage_price = trade_params.price_tick * params.slippage_ticks
    return open_price - slippage_price if direction == "long" else open_price + slippage_price


def _gross_pnl(direction: str, entry_price: float, exit_price: float, volume: int, multiplier: int) -> float:
    if direction == "long":
        return (exit_price - entry_price) * volume * multiplier
    return (entry_price - exit_price) * volume * multiplier


def commission_for_trade(
    entry_price: float,
    exit_price: float,
    volume: int,
    entry_params: TradeParams,
    exit_params: TradeParams,
) -> float:
    if entry_params.cost_rule is not None or exit_params.cost_rule is not None:
        if entry_params.cost_rule is None or exit_params.cost_rule is None:
            raise ValueError("canonical commission lineage must exist on both trade legs")
        same_day = bool(entry_params.trading_day and entry_params.trading_day == exit_params.trading_day)
        close_fee = (
            exit_params.cost_rule.close_today_fee
            if same_day and exit_params.cost_rule.close_today_fee is not None
            else exit_params.cost_rule.close_fee
        )
        return _leg_commission(
            entry_price,
            volume,
            entry_params.contract_multiplier,
            entry_params.cost_rule.fee_type,
            entry_params.cost_rule.open_fee,
        ) + _leg_commission(
            exit_price,
            volume,
            exit_params.contract_multiplier,
            exit_params.cost_rule.fee_type,
            close_fee,
        )
    return _legacy_commission(entry_price, exit_price, volume, entry_params)


def _legacy_commission(entry_price: float, exit_price: float, volume: int, trade_params: TradeParams) -> float:
    by_money = 0.0
    if trade_params.commission_rate is not None:
        by_money = (entry_price + exit_price) * volume * trade_params.contract_multiplier * trade_params.commission_rate
    by_contract = 0.0
    if trade_params.commission_per_contract is not None:
        by_contract = trade_params.commission_per_contract * volume * 2
    return by_money + by_contract


def _leg_commission(price: float, volume: int, multiplier: int, fee_type: str, fee: float) -> float:
    if fee_type == "rate":
        return price * volume * multiplier * fee
    if fee_type == "fixed":
        return volume * fee
    raise ValueError(f"unsupported commission fee_type: {fee_type}")


def _bar_datetime(bar: Any) -> datetime:
    value = _bar_value(bar, "datetime")
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))


def _date_text(value: Any) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return date.fromisoformat(str(value)[:10]).isoformat()


def _bar_float(bar: Any, *names: str) -> float:
    for name in names:
        value = _bar_value(bar, name)
        if value is not None:
            return float(value)
    raise ValueError(f"bar missing numeric field: {names}")


def _bar_value(bar: Any, name: str) -> Any:
    if isinstance(bar, dict):
        return bar.get(name)
    return getattr(bar, name, None)


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


def _scalar_or_none(value: Any) -> Any:
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, bool):
        return value
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        value = float(value)
    if isinstance(value, float):
        if not np.isfinite(value):
            return None
        return round(value, 6)
    return value


def _symbol_root(symbol: str) -> str:
    normalized = symbol.split(".", 1)[0]
    return "".join(char for char in normalized if not char.isdigit()) or normalized


HuoTianDaYouStrict = HuoTianDaYouStrictStrategy
