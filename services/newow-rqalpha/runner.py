"""RQAlpha's native P1 historical account for a frozen physical contract."""

import platform
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

import rqalpha
from rqalpha import api, main
from rqalpha.const import MATCHING_TYPE, PERSIST_MODE, POSITION_EFFECT, RUN_TYPE
from rqalpha.core.events import EVENT
from rqalpha.environment import Environment
from rqalpha.mod.rqalpha_mod_sys_simulation.simulation_broker import SimulationBroker
from rqalpha.model.order import LimitOrder, MarketOrder
from rqalpha.utils import RqAttrDict
from rqalpha.utils.config import default_config
from rqalpha.utils.functools import clear_all_cached_functions

from frozen_market import (
    ASIA_SHANGHAI,
    ONE_MINUTE,
    FrozenDataSource,
    FrozenMarket,
    SignalPriceBoard,
    local_naive,
    valid_decimal,
)

HISTORICAL_AVAILABILITY = timedelta(seconds=2)
SIMULATION = {
    "matching_type": "next_bar", "signal": False, "price_limit": True,
    "volume_limit": False, "inactive_limit": True, "slippage_model": "PriceRatioSlippage",
    "slippage": 0, "management_fee": [],
}


@dataclass(frozen=True, slots=True)
class Signal:
    signal_id: str
    contract: str
    day: date
    bar_end: datetime
    action: str
    direction: str = "LONG"
    limit_price: Decimal | None = None
    available_at: datetime | None = None

    def __post_init__(self):
        if (not self.signal_id or self.action not in ("BUILD", "CLEAR", "HOLD")
                or self.direction not in ("LONG", "SHORT")
                or self.limit_price is not None and not valid_decimal(self.limit_price, positive=True)):
            raise ValueError("INVALID_SIGNAL")
        if local_naive(self.bar_end).date() != self.day:
            raise ValueError("SIGNAL_DAY_MISMATCH")
        if self.available_at is not None and (
            self.available_at.utcoffset() is None or self.available_at < self.bar_end
        ):
            raise ValueError("SIGNAL_AVAILABILITY_INVALID")


def _config(market, capital, scratch):
    # RQAlpha's public parse_config also reads user and cwd configs. Read only
    # the pinned package defaults and supply the runtime values explicitly.
    config = RqAttrDict(default_config())
    base = config.base
    base.start_date, base.end_date = market.daily[0].day, market.daily[-1].day
    base.run_type, base.frequency = RUN_TYPE.BACKTEST, "1m"
    base.accounts, base.init_positions, base.future_info = {"FUTURE": float(capital)}, [], {}
    base.data_bundle_path = str(Path(scratch) / "bundle-must-not-exist")
    base.rqdatac_uri = "disabled"
    base.auto_update_bundle = False
    base.futures_time_series_trading_parameters = True
    base.partial_fill_on_insufficient_cash = False
    base.persist, base.persist_mode = False, PERSIST_MODE.REAL_TIME
    base.forced_liquidation = False
    config.extra.log_level = "error"
    config.mod.sys_progress.enabled = False
    config.mod.sys_analyser.enabled = False
    config.mod.sys_scheduler.enabled = False
    config.mod.sys_accounts.futures_settlement_price_type = "settlement"
    config.mod.sys_simulation.update(SIMULATION)
    config.mod.frozen_market = RqAttrDict({"lib": "frozen_market", "enabled": True, "priority": 0, "market": market})
    return config


def _attempts(market, signals, minute_selector=None):
    seen, attempts, scheduled = set(), [], {}
    previous = None
    for signal in signals:
        if signal.contract != market.contract:
            raise ValueError("SIGNAL_CONTRACT_MISMATCH")
        bar_end = signal.bar_end.astimezone(ASIA_SHANGHAI)
        if signal.signal_id in seen or previous is not None and previous >= bar_end:
            raise ValueError("SIGNALS_NOT_STRICTLY_ORDERED")
        seen.add(signal.signal_id)
        previous = bar_end
        session = next((item for item in market.sessions
                        if item.day == signal.day and item.start < bar_end <= item.end), None)
        if (session is None or bar_end.second or bar_end.microsecond
                or (bar_end != session.end and (bar_end - session.start) % (5 * ONE_MINUTE))):
            raise ValueError("SIGNAL_5M_SESSION_MISMATCH")
        if signal.limit_price is not None and signal.limit_price % market.tick:
            raise ValueError("SIGNAL_LIMIT_TICK_MISMATCH")

        available = (signal.available_at or bar_end + HISTORICAL_AVAILABILITY).astimezone(ASIA_SHANGHAI)
        opens = tuple(end - ONE_MINUTE for end in session.minute_ends())
        candidate_open = (minute_selector(available, opens) if minute_selector is not None
                          else next((opening for opening in opens if opening > available), None))
        attempt = {"signal_id": signal.signal_id, "contract": market.contract, "action": signal.action,
                   "direction_requested": signal.direction if signal.action == "BUILD" else None,
                   "signal_bar_end": bar_end, "signal_available_at": available,
                   "candidate_open_at": None, "candidate_bar_end": None, "reason": None}
        attempts.append(attempt)
        if signal.action == "HOLD":
            attempt["reason"] = "HOLD"
        elif candidate_open is None:
            attempt["reason"] = "NO_SAME_SESSION_CANDIDATE"
        else:
            if candidate_open not in opens or candidate_open <= available:
                raise ValueError("SIGNAL_CANDIDATE_INVALID")
            candidate_open = candidate_open.astimezone(ASIA_SHANGHAI)
            candidate_end = candidate_open + ONE_MINUTE
            attempt.update(candidate_open_at=candidate_open, candidate_bar_end=candidate_end)
            # This is the native preceding bar label, not a model timestamp for
            # the research decision. Its later close is hidden at submission.
            scheduled[local_naive(candidate_open)] = (signal, attempt)
    return attempts, scheduled


def _timestamp(value):
    return value.replace(tzinfo=ASIA_SHANGHAI)


def _account_snapshot(account):
    return {
        "cash": float(account.cash), "equity": float(account.total_value),
        "margin": float(account.margin), "frozen_cash": float(account.frozen_cash),
        "positions": [{"contract": pos.order_book_id, "direction": pos.direction.name, "quantity": int(pos.quantity),
                       "average_price": float(pos.avg_price), "last_price": float(pos.last_price),
                       "position_equity": float(pos.equity), "today_quantity": int(pos.today_quantity),
                       "old_quantity": int(pos.old_quantity)} for pos in account.get_positions()],
    }


def run_proof(
    market: FrozenMarket, signals: tuple[Signal, ...], capital: Decimal, *,
    rollover_boundary=False, decide=None, minute_selector=None,
):
    """Run one bounded day-session segment serially in a standalone Python process."""
    if rqalpha.__version__ != "6.3.0":
        raise RuntimeError("UNSUPPORTED_RQALPHA_VERSION")
    if not valid_decimal(capital, positive=True):
        raise ValueError("INVALID_INITIAL_CAPITAL")

    if signals and decide is not None:
        raise ValueError("MIXED_SIGNAL_SOURCES")
    attempts, scheduled = _attempts(market, signals, minute_selector)
    minutes = {local_naive(row.end): row for row in market.minutes}
    last_bar_by_day = {row.day: row for row in market.minutes}
    fills, settlements, creation_rejections = [], [], []
    open_orders = {}
    native = {}
    contract = market.contract

    def admit_decisions(env, *, settling=False):
        if decide is None:
            return
        dt = env.calendar_dt
        positions = tuple(env.get_account(contract).get_positions())
        signal_batch = tuple(decide(_timestamp(dt), positions, tuple(fills)))
        new_attempts, new_candidates = _attempts(market, signal_batch, minute_selector)
        if attempts and new_attempts and attempts[-1]["signal_bar_end"] >= new_attempts[0]["signal_bar_end"]:
            raise ValueError("SIGNALS_NOT_STRICTLY_ORDERED")
        if any(row["signal_available_at"] > _timestamp(dt) for row in new_attempts):
            raise ValueError("SIGNAL_NOT_YET_AVAILABLE")
        if new_candidates and (settling or min(new_candidates) < dt or scheduled.keys() & new_candidates.keys()):
            raise ValueError("EXPECTED_NATIVE_SUBMISSION_EVENT_MISSING")
        attempts.extend(new_attempts)
        scheduled.update(new_candidates)

    def on_trade(event):
        trade = event.trade
        if trade.order_id not in open_orders:
            raise RuntimeError("UNEXPECTED_NATIVE_TRADE")
        _, attempt = open_orders[trade.order_id]
        event_at = _timestamp(trade.datetime)
        if event_at != attempt["candidate_bar_end"] or trade.order_book_id != contract or trade.last_quantity != 1:
            raise RuntimeError("NATIVE_FILL_OUTSIDE_FIRST_CANDIDATE")
        native_close_today_amount = int(trade.close_today_amount)
        # RQAlpha may report this raw amount on OPEN; an opening trade closes no lots.
        close_today_quantity = 0 if trade.position_effect is POSITION_EFFECT.OPEN else native_close_today_amount
        fills.append({
            "signal_id": attempt["signal_id"], "contract": trade.order_book_id, "native_order_id": trade.order_id,
            "native_trade_id": trade.exec_id, "native_event_at": event_at,
            "native_trading_at": _timestamp(trade.trading_datetime),
            "modeled_fill_at": attempt["candidate_open_at"], "price": float(trade.last_price),
            "commission": float(trade.commission), "tax": float(trade.tax), "fee": float(trade.transaction_cost),
            "quantity": int(trade.last_quantity), "close_today_quantity": close_today_quantity,
            "native_close_today_amount": native_close_today_amount,
            "side": trade.side.name, "direction": trade.position_direction.name,
            "position_effect": trade.position_effect.name,
        })

    def pre_settlement(_):
        env = Environment.get_instance()
        admit_decisions(env, settling=True)
        day = env.trading_dt.date()
        settlements.append({"day": day, "native_event_at": _timestamp(env.calendar_dt),
                            "last_bar_close": last_bar_by_day[day].close,
                            "before": _account_snapshot(env.get_account(contract))})

    def post_settlement(_):
        env = Environment.get_instance()
        settlements[-1]["after"] = _account_snapshot(env.get_account(contract))

    def init(_):
        env = Environment.get_instance()
        if (not isinstance(env.data_source, FrozenDataSource) or not isinstance(env.price_board, SignalPriceBoard)
                or not isinstance(env.broker, SimulationBroker) or env.rqdatac_init
                or env.config.mod.sys_simulation.matching_type is not MATCHING_TYPE.NEXT_BAR_OPEN):
            raise RuntimeError("NATIVE_OFFLINE_CONFIGURATION_MISMATCH")
        native.update(data_source=type(env.data_source).__name__, broker=type(env.broker).__name__,
                      event_source=type(env.event_source).__name__, account=type(env.get_account(contract)).__name__,
                      enabled_mods=list(env.mod_dict), config=env.config.mod.sys_simulation.convert_to_dict())
        native["config"]["matching_type"] = env.config.mod.sys_simulation.matching_type.name
        env.event_bus.add_listener(EVENT.TRADE, on_trade)
        env.event_bus.add_listener(EVENT.PRE_SETTLEMENT, pre_settlement)
        env.event_bus.add_listener(EVENT.POST_SETTLEMENT, post_settlement)
        env.event_bus.add_listener(EVENT.ORDER_CREATION_REJECT, lambda event: creation_rejections.append(event.reason))
        api.subscribe(contract)

    def handle_bar(_, __):
        env = Environment.get_instance()
        dt = env.calendar_dt
        for order_id, (order, attempt) in list(open_orders.items()):
            if _timestamp(dt) != attempt["candidate_bar_end"]:
                raise RuntimeError("EXPECTED_NATIVE_CANDIDATE_EVENT_MISSING")
            if not order.is_final():
                env.broker.cancel_order(order)
                attempt["reason"] = "FIRST_CANDIDATE_EXPIRED"
            else:
                attempt["reason"] = order.message or order.status.name
            attempt.update(native_status=order.status.name, native_status_reason=order.message)
            del open_orders[order_id]

        admit_decisions(env)
        item = scheduled.pop(dt, None)
        if item is None:
            return
        signal, attempt = item
        positions = tuple(env.get_account(contract).get_positions())
        if any(pos.quantity != 1 or pos.order_book_id != contract for pos in positions) or len(positions) > 1:
            raise RuntimeError("NATIVE_POSITION_OUTSIDE_ONE_LOT_POLICY")
        if signal.action == "BUILD" and positions:
            attempt["reason"] = "POSITION_ALREADY_OPEN"
            return
        if signal.action == "CLEAR" and not positions:
            attempt["reason"] = "NO_OPEN_POSITION"
            return

        reference = minutes[local_naive(signal.bar_end)].close
        style = MarketOrder() if signal.limit_price is None else LimitOrder(float(signal.limit_price))
        kwargs = {}
        if signal.action == "BUILD":
            submit = api.buy_open if signal.direction == "LONG" else api.sell_open
        else:
            position = positions[0]
            submit = api.sell_close if position.direction.name == "LONG" else api.buy_close
            kwargs["close_today"] = position.today_quantity == 1
        attempt.update(order_reference_price=reference, limit_price=signal.limit_price)
        creation_rejections.clear()
        with env.price_board.submitting(contract, reference):
            order = submit(contract, 1, style=style, **kwargs)
        if not order:
            attempt["reason"] = creation_rejections[-1] if creation_rejections else "NATIVE_ORDER_CREATION_REJECTED"
            return
        attempt.update(native_order_id=order.order_id, native_order_at=_timestamp(order.datetime),
                       native_trading_at=_timestamp(order.trading_datetime),
                       native_frozen_price=float(order.frozen_price),
                       native_side=order.side.name, native_position_effect=order.position_effect.name,
                       native_quantity=int(order.quantity))
        open_orders[order.order_id] = (order, attempt)

    with TemporaryDirectory(prefix="guiyi-rqalpha-") as scratch:
        clear_all_cached_functions()
        main.run(_config(market, capital, scratch), user_funcs={"init": init, "handle_bar": handle_bar})

    if scheduled or open_orders or len(settlements) != len(market.daily):
        raise RuntimeError("INCOMPLETE_NATIVE_EXECUTION_TRACE")
    for attempt in attempts:
        candidate_end = attempt["candidate_bar_end"]
        if candidate_end is not None:
            attempt["frozen_candidate"] = asdict(minutes[local_naive(candidate_end)])
    terminal_status = "FLAT"
    if settlements[-1]["after"]["positions"]:
        terminal_status = "ROLLOVER_INTERRUPTED" if rollover_boundary else "OPEN_MARKED_AT_SETTLEMENT"

    return {
        "scope": "P1_A_OFFLINE_PROOF", "engine_version": rqalpha.__version__, "python": platform.python_version(),
        "platform": platform.platform(), "architecture": platform.machine(), "contract": contract,
        "exchange": market.exchange, "initial_equity": capital, "tick": market.tick, "multiplier": market.multiplier,
        "availability_assumption": "historical_completed_5m_plus_2_seconds_v1", "expiry": "first_candidate_only",
        "rqdatac_uri": "disabled", "auto_update_bundle": False, "daily_facts": [asdict(day) for day in market.daily],
        "sessions": [asdict(session) for session in market.sessions], "source_m1_count": len(market.minutes),
        "native": native, "attempts": attempts, "fills": fills, "settlements": settlements,
        "terminal_status": terminal_status,
    }
