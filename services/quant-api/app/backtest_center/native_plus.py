"""Fixed native execution for a single SHFE FU physical contract."""
from __future__ import annotations

from collections.abc import Callable
from contextlib import contextmanager
from datetime import datetime, time, timedelta
from decimal import Decimal, localcontext
from math import isfinite
import os
from pathlib import Path
import sys
from urllib.parse import urlsplit

from guiyi_quant.newow.decision_adapter import (
    CompletedMarketPayload,
    ExecutionContext,
    MarketSource,
    V2Strategy,
    seed_decision_state,
    step_completed,
)
from guiyi_quant.newow.models import NewowDailyBar
from guiyi_quant.newow.product_contracts import ActionKind, ProductBar, ProductFrequency
from guiyi_quant.newow.profile import NEWOW_TREND_D1_PAGE_V2
from guiyi_quant.reference_trading.adapters import strategy_input_fingerprint

from .codec import digest
from .errors import BacktestError
from .plus_costs import DatedCostDataSource, DatedCosts
from .plus_inputs import DAY_SESSIONS, MINUTE, InputSlice, Minute, NativeConfig, finite, local, preflight
from .plus_reconcile import (
    ACCOUNT_BINARY_TOLERANCE,
    MONEY_CONTEXT,
    MONEY_POLICY,
    ZERO,
    AccountWitness,
    candidate_quote,
    metrics,
    money,
    parse_rates,
    raw_money,
    text,
    trade_amounts,
)

AVAILABILITY = timedelta(seconds=2)
AVAILABILITY_POLICY = "historical_completed_5m_plus_2_seconds_v1"
EXECUTION_POLICY_VERSION = "single_physical_long_next_same_session_1m_v1"
ROLL_POLICY_VERSION = "interrupt_single_physical_v1"


class LicenseChannel:
    """Allow the pinned vendor runtime to verify entitlement without data fallback."""

    def __init__(self):
        self.inside = False
        self.calls = 0
        self.blocked = False
        self.granted_transport = False
        self.active = True
        self.error: str | None = None

    def audit(self, event, _):
        if self.active and not self.inside and event in {
            "socket.connect", "socket.sendto", "socket.getaddrinfo",
            "socket.gethostbyname", "socket.gethostbyaddr", "socket.getnameinfo",
        }:
            self.blocked = True
            raise BacktestError("PLUS_NON_LICENSE_NETWORK_BLOCKED")

    @contextmanager
    def guard(self):
        from requests import RequestException, Session

        original = Session.request
        channel = self

        def request(session, method, url, **kwargs):
            target = urlsplit(url)
            if (
                self.calls or method.upper() != "GET" or target.scheme != "https"
                or target.netloc != "www.ricequant.com"
                or target.path != "/api/rqlicense/rqsdk/get_permissions"
                or target.query or target.fragment
                or kwargs.get("params", {}).get("permission_id") != "rqsdk__mod_backtest_future"
            ):
                self.blocked = True
                raise BacktestError("PLUS_NON_LICENSE_NETWORK_BLOCKED")
            self.calls += 1
            self.inside = True
            try:
                kwargs.update(timeout=10, allow_redirects=False, verify=True)
                response = original(session, method, url, **kwargs)
                if response.status_code != 200:
                    self.error = "PLUS_LICENSE_UNVERIFIED"
                    raise BacktestError(self.error)
                self.granted_transport = True
                return response
            except RequestException:
                self.error = "PLUS_LICENSE_SERVICE_UNREACHABLE"
                raise BacktestError(self.error) from None
            finally:
                self.inside = False

        sys.addaudithook(channel.audit)
        Session.request = request
        try:
            yield
        finally:
            Session.request = original
            self.active = False


class SubmissionPrice:
    """Delegate native pricing except for the market order's admission quote."""
    def __init__(self, native):
        self.native = native
        self.override: tuple[str, float] | None = None

    @contextmanager
    def freeze(self, contract: str, price: Decimal):
        self.override = (contract, float(price))
        try:
            yield
        finally:
            self.override = None

    def get_last_price(self, contract):
        if self.override is not None:
            if contract != self.override[0]:
                raise BacktestError("PLUS_FOREIGN_CONTRACT_DURING_SUBMISSION")
            return self.override[1]
        return self.native.get_last_price(contract)

    def __getattr__(self, attribute):
        return getattr(self.native, attribute)


def _bar_input(rows: list[Minute], packet: InputSlice, config: NativeConfig, owner: str) -> CompletedMarketPayload:
    first, last = rows[0], rows[-1]
    bar = NewowDailyBar(
        product="fu", physical_contract=config.contract, segment_id=owner,
        trading_day=last.session.day, bar_end=last.end, open=first.open,
        high=max(row.high for row in rows), low=min(row.low for row in rows),
        close=last.close, volume=sum(row.volume for row in rows), open_interest=last.open_interest,
        source_identity=packet.dataset_revision, observation_eligible=last.session.day >= config.start,
        completed=True, series_kind="physical_futures",
    )
    return CompletedMarketPayload(
        ProductBar(bar, ProductFrequency.FIVE_MINUTE, series_kind="physical_futures"),
        MarketSource.RQALPHA_PLUS, packet.dataset_revision, f"{config.contract}:1m:{last.end.isoformat()}", owner,
        (last.session.start, last.session.end), last.end + AVAILABILITY, AVAILABILITY_POLICY,
        confirmed_at=last.end + AVAILABILITY, observed_at=last.end, turnover=sum((row.turnover for row in rows), ZERO),
    )


def _candidate(payload: CompletedMarketPayload, delay: int = 0) -> datetime | None:
    # The order callback is tagged with the predecessor's close/open boundary.
    # That minute's close is unavailable at the modeled order time.
    opening = payload.available_at.replace(second=0, microsecond=0) + (delay + 1) * MINUTE
    return opening if opening + MINUTE <= payload.session[1] else None


def _config(native: NativeConfig, packet: InputSlice):
    from rqalpha.const import PERSIST_MODE, RUN_TYPE
    from rqalpha.utils import RqAttrDict
    from rqalpha.utils.config import default_config

    # Use the installed Plus defaults, without local project/user overrides.
    cfg = RqAttrDict(default_config())
    base = cfg.base
    base.start_date, base.end_date = next(iter(packet.days)), next(reversed(packet.days))
    base.data_bundle_path = str(packet.root)
    base.frequency, base.run_type = "1m", RUN_TYPE.BACKTEST
    base.accounts, base.init_positions, base.future_info = {"FUTURE": float(native.initial_capital)}, [], {}
    base.rqdatac_uri = "disabled"
    base.auto_update_bundle = base.persist = base.forced_liquidation = False
    base.partial_fill_on_insufficient_cash = False
    base.capital_gain_tax_rate = 0
    base.futures_time_series_trading_parameters = True
    base.persist_mode = PERSIST_MODE.REAL_TIME
    cfg.extra.log_level = "error"
    cfg.extra.log_file = None
    allow = {"ricequant_data", "sys_simulation", "sys_accounts", "sys_risk", "sys_transaction_cost", "sys_analyser"}
    for name in cfg.mod.__dict__:
        cfg.mod.__dict__[name].enabled = name in allow
    cfg.mod.ricequant_data.tick_type = "h5"
    cfg.mod.ricequant_data.night_trading = True
    cfg.mod.sys_accounts.futures_settlement_price_type = "settlement"
    cfg.mod.sys_simulation.update({
        "matching_type": "next_bar", "signal": False, "price_limit": True, "volume_limit": True,
        "volume_percent": 1, "inactive_limit": True, "slippage_model": "TickSizeSlippage",
        "slippage": native.slippage_ticks, "management_fee": [],
    })
    cfg.mod.sys_transaction_cost.update({"futures_commission_multiplier": float(native.commission_multiplier)})
    cfg.mod.sys_analyser.update({"benchmark": None, "record": True, "output_file": None,
                                "report_save_path": None, "plot": False, "plot_save_file": None})
    return cfg


def _input_identity(packet: InputSlice, costs: DatedCosts) -> str:
    return digest({"market_slice": packet.slice_hash, "cost_rows": costs.rows_sha256})


class NativeRun:
    def __init__(self, packet: InputSlice, config: NativeConfig, run_id: str, admit: Callable[[dict], None],
                 license_channel: LicenseChannel, costs: DatedCosts):
        self.packet = packet
        self.config = config
        self.run_id = run_id
        self.admit = admit
        self.license_channel = license_channel
        self.costs = costs
        self.contract = config.contract
        self.state = seed_decision_state()
        self.rows: list[Minute] = []
        self.pending: CompletedMarketPayload | None = None
        self.outstanding: tuple[object, dict] | None = None
        self.awaiting_submission: tuple[ActionKind, CompletedMarketPayload, datetime, dict] | None = None
        self.fills: list[dict] = []
        self.attempts: list[dict] = []
        self.equity: list[dict] = []
        self.bars: list[dict] = []
        self.markers: list[dict] = []
        self.settlements: list[dict] = []
        self.pre_settlement_account: dict | None = None
        self.fills_hash = strategy_input_fingerprint({"run_id": run_id, "native_fills": []})
        self.account_as_of = packet.sessions[0].start
        self.visited = iter(packet.minutes)
        self.peak = config.initial_capital
        self.evaluation_days = [day.isoformat() for day in packet.days if day >= config.start]
        self.initial_session = next(session.start for session in packet.sessions if session.day >= config.start)
        self.started = False
        self.error: str | None = None

    def checked(self, callback):
        def invoke(*args):
            try:
                # Installed Plus imports stock APIs which set the ambient precision to 10.
                with localcontext(MONEY_CONTEXT):
                    return callback(*args)
            except BacktestError as exc:
                self.error = exc.code
                raise
        return invoke

    def init(self, _):
        from rqalpha import api
        from rqalpha.const import INSTRUMENT_TYPE, MATCHING_TYPE
        from rqalpha.core.events import EVENT
        from rqalpha.environment import Environment
        from rqalpha.mod.rqalpha_mod_sys_simulation.simulation_broker import SimulationBroker
        from rqalpha_mod_ricequant_data.data_sources.bundle_data_source import BundleDataSource

        self.env = env = Environment.get_instance()
        if (
            not isinstance(env.data_source, BundleDataSource) or not isinstance(env.broker, SimulationBroker)
            or env.rqdatac_init or env.config.mod.sys_simulation.matching_type is not MATCHING_TYPE.NEXT_BAR_OPEN
            or (env.config.base.start_date, env.config.base.end_date) != (
                next(iter(self.packet.days)), next(reversed(self.packet.days))
            )
        ):
            raise BacktestError("PLUS_NATIVE_RUNTIME_CONTRACT_MISMATCH")
        if not self.license_channel.granted_transport:
            raise BacktestError("PLUS_LICENSE_UNVERIFIED")
        ins = env.data_proxy.instrument(self.contract)
        if (
            ins is None or ins.type != INSTRUMENT_TYPE.FUTURE or ins.exchange != "SHFE"
            or ins.order_book_id != self.contract or ins.underlying_symbol != "FU"
            or ins.listed_date.date() > next(iter(self.packet.days))
            or ins.de_listed_date.date() < next(reversed(self.packet.days))
        ):
            raise BacktestError("PLUS_PHYSICAL_CONTRACT_OUTSIDE_LIFETIME")
        clocks = ((time(21), time(23)), *DAY_SESSIONS)
        expected_sessions = tuple((time(opening.hour, opening.minute + 1), close) for opening, close in clocks)
        if tuple((window.start, window.end) for window in ins.trading_hours) != expected_sessions:
            raise BacktestError("PLUS_NATIVE_INSTRUMENT_SESSIONS_UNVERIFIED")
        self.expiry = ins.de_listed_date.date()
        self.owner = f"rqalpha_plus:{self.contract}:{ins.listed_date.date().isoformat()}"
        self.tick = finite(ins.tick_size(), positive=True)
        multiplier = finite(ins.contract_multiplier, positive=True)
        if multiplier != int(multiplier):
            raise BacktestError("PLUS_NATIVE_CONTRACT_MULTIPLIER_INVALID")
        self.multiplier = int(multiplier)
        if any(price % self.tick for row in self.packet.minutes.values()
               for price in (row.open, row.high, row.low, row.close)):
            raise BacktestError("PLUS_INPUT_PRICE_OFF_TICK_GRID")
        self.instrument = ins
        self.cost_data_source = DatedCostDataSource(env.data_source, self.costs)
        env.set_data_source(self.cost_data_source)
        env.data_proxy._data_source = self.cost_data_source
        self.rates = {
            day: parse_rates(env.data_proxy.get_futures_trading_parameters(self.contract, datetime.combine(day, datetime.min.time())))
            for day in self.packet.days
        }
        for day, facts in self.packet.days.items():
            settlement = env.data_proxy.get_settle_price(self.contract, datetime.combine(day, datetime.min.time()))
            if finite(settlement, positive=True) != facts.settlement:
                raise BacktestError("PLUS_NATIVE_SETTLEMENT_PRICE_MISMATCH")
        self.witness = AccountWitness(self.config.initial_capital, self.contract, self.multiplier)
        self.board = SubmissionPrice(env.price_board)
        env.set_price_board(self.board)
        env.data_proxy._price_board = self.board
        env.event_bus.add_listener(EVENT.TRADE, self.checked(self.fill))
        env.event_bus.add_listener(EVENT.PRE_BAR, self.checked(self.guard_candidate))
        env.event_bus.add_listener(EVENT.PRE_SETTLEMENT, self.checked(self.pre_settlement))
        env.event_bus.add_listener(EVENT.POST_SETTLEMENT, self.checked(self.post_settlement))
        api.subscribe(self.contract)
        snapshot = self.packet.snapshot()
        snapshot.update(self.costs.snapshot())
        snapshot["data_files"]["dated_cost_profile.json"] = self.costs.artifact_sha256
        snapshot["input_sha256"] = _input_identity(self.packet, self.costs)
        snapshot.update({
            "evaluation_trading_days": self.evaluation_days,
            "physical_contract": self.contract, "tick_size": text(self.tick), "contract_multiplier": self.multiplier,
            "source_instrument": "SHFE", "execution_policy_version": EXECUTION_POLICY_VERSION,
            "roll_policy_version": ROLL_POLICY_VERSION, "money_policy": MONEY_POLICY,
            "availability_policy": AVAILABILITY_POLICY, "execution_delay_minutes": self.config.execution_delay_minutes,
            "effective_costs": {day.isoformat(): {
                name: text(value) if isinstance(value, Decimal) else value for name, value in rates.items()
            } for day, rates in self.rates.items()},
        })
        self.admit(snapshot)
        self.started = True

    @property
    def account(self):
        return self.env.get_account(self.contract)

    def advance(self, at: datetime, *, trading: bool) -> None:
        payload = self.pending
        if payload is None or payload.available_at > at:
            return
        self.pending = None
        eligible = payload.bar.bar.observation_eligible
        position = Decimal(self.witness.open_fill is not None)
        context = ExecutionContext(
            self.run_id, self.packet.slice_hash, (V2Strategy.TREND,), V2Strategy.TREND,
            self.account_as_of, self.fills_hash, self.fills_hash, position, self.contract,
        )
        self.state, (decision,) = step_completed(self.state, payload.completed_input(), context)
        if not eligible:
            return
        bar = payload.bar.bar
        self.bars.append({"at": local(bar.bar_end).isoformat(), "open": text(bar.open),
                          "high": text(bar.high), "low": text(bar.low), "close": text(bar.close),
                          "trading_day": bar.trading_day.isoformat(), "contract": self.contract})
        if decision.main_action is None:
            return
        reason = decision.reason
        opening = _candidate(payload, self.config.execution_delay_minutes)
        attempt = {
            "signal_id": decision.decision_id, "action": decision.main_action.value, "reason": reason,
            "signal_bar_end": local(bar.bar_end).isoformat(), "signal_observed_at": payload.observed_at.isoformat(),
            "signal_confirmed_at": payload.confirmed_at.isoformat(), "signal_available_at": payload.available_at.isoformat(),
            "effective_after": payload.available_at.isoformat(), "input_ref": decision.input_ref,
            "formula_versions": decision.formula_versions, "product_profiles": decision.profiles,
            "contract": self.contract, "trading_day": bar.trading_day.isoformat(),
        }
        self.attempts.append(attempt)
        self.markers.append({"at": local(bar.bar_end).isoformat(), "kind": decision.main_action.value,
                             "price": text(bar.close), "label": decision.main_action.value,
                             "signal_id": decision.decision_id, "contract": self.contract})
        if not decision.execution_candidate:
            return
        if opening is None:
            attempt["reason"] = "NO_SAME_SESSION_CANDIDATE"
            return
        if not trading or at > opening or self.awaiting_submission is not None:
            raise BacktestError("PLUS_NATIVE_ORDER_CALLBACK_MISSING")
        self.awaiting_submission = (decision.main_action, payload, opening, attempt)

    def submit(self, action: ActionKind, payload: CompletedMarketPayload, opening: datetime, attempt: dict) -> None:
        from rqalpha import api

        reference = payload.bar.bar.close
        attempt.update(candidate_open_at=opening.isoformat(), candidate_bar_end=(opening + MINUTE).isoformat(),
                       modeled_order_at=opening.isoformat(), order_reference_price=text(reference))
        with self.board.freeze(self.contract, reference):
            if action is ActionKind.BUILD:
                order = api.buy_open(self.contract, 1)
            else:
                position, = (p for p in self.account.get_positions() if p.quantity)
                order = api.sell_close(self.contract, 1, close_today=position.today_quantity == 1)
        if not order:
            attempt["reason"] = "NATIVE_ORDER_REJECTED"
            return
        if isinstance(order, list) or local(order.datetime) != opening or order.order_book_id != self.contract:
            raise BacktestError("PLUS_NATIVE_ORDER_IDENTITY_MISMATCH")
        attempt.update(native_order_id=str(order.order_id), native_order_at=local(order.datetime).isoformat(),
                       native_order_trading_at=local(order.trading_datetime).isoformat(),
                       native_frozen_price=raw_money(reference, order.frozen_price))
        self.outstanding = order, attempt

    def guard_candidate(self, _) -> None:
        # In PRE_BAR the native candidate is available to the matcher. A
        # slippage-adjusted quote beyond the limit must be canceled before it
        # reaches the native BAR matcher, which checks the raw open first.
        if self.outstanding is None:
            return
        order, attempt = self.outstanding
        stamp = local(self.env.calendar_dt)
        if stamp.isoformat() != attempt["candidate_bar_end"]:
            raise BacktestError("PLUS_NATIVE_ORDER_EXPIRY_CLOCK_MISMATCH")
        candidate = self.packet.minutes.get(stamp)
        if candidate is None:
            raise BacktestError("PLUS_NATIVE_CANDIDATE_MINUTE_MISSING")
        _, reason = candidate_quote(
            candidate, self.packet.days[candidate.session.day], self.tick, self.config.slippage_ticks,
            buying=attempt["action"] == ActionKind.BUILD.value,
        )
        if reason and not order.is_final():
            self.env.broker.cancel_order(order)
            attempt["candidate_guard"] = reason

    def fill(self, event) -> None:
        trade = event.trade
        if self.outstanding is None:
            if getattr(event, "order", None) is None and self.witness.open_fill and self.env.trading_dt.date() == self.expiry:
                raise BacktestError("ROLLOVER_INTERRUPTED")
            raise BacktestError("PLUS_UNEXPECTED_NATIVE_FILL")
        order, attempt = self.outstanding
        stamp = local(trade.datetime)
        modeled = datetime.fromisoformat(attempt["candidate_open_at"])
        native_trading = local(trade.trading_datetime)
        candidate = self.packet.minutes.get(stamp)
        prior = self.witness.open_fill
        effect = "OPEN" if attempt["action"] == "BUILD" else (
            "CLOSE_TODAY" if prior is not None and prior["day"] == native_trading.date() else "CLOSE"
        )
        if (
            trade.order_id != order.order_id or trade.order_book_id != self.contract
            or trade.last_quantity != 1 or trade.position_direction.name != "LONG"
            or trade.position_effect.name != effect or trade.side.name != ("BUY" if effect == "OPEN" else "SELL")
            or stamp != modeled + MINUTE or candidate is None or candidate.session.day != native_trading.date()
            or native_trading.date().isoformat() != attempt["trading_day"]
            or (effect != "OPEN" and trade.close_today_amount != int(effect == "CLOSE_TODAY"))
        ):
            raise BacktestError("PLUS_NATIVE_TRADE_IDENTITY_OR_TIME_MISMATCH")
        price, fee = trade_amounts(
            self.rates[candidate.session.day], effect, candidate, self.packet.days[candidate.session.day],
            self.tick, self.multiplier, slippage=self.config.slippage_ticks,
            commission_multiplier=self.config.commission_multiplier,
        )
        row = {
            "signal_id": attempt["signal_id"], "contract": self.contract, "position_effect": effect,
            "side": trade.side.name, "quantity": 1, "direction": "LONG", "modeled_fill_at": modeled.isoformat(),
            "native_fill_at": stamp.isoformat(), "native_fill_trading_at": native_trading.isoformat(),
            "native_order_at": attempt["native_order_at"], "native_order_id": str(order.order_id),
            "native_trade_id": str(trade.exec_id), "trading_day": candidate.session.day.isoformat(),
            "native_close_today_amount": trade.close_today_amount, "price": text(price), "fee": text(money(fee)),
            "native_amounts": {"price": raw_money(price, trade.last_price), "fee": raw_money(fee, trade.transaction_cost),
                               "commission": raw_money(fee, trade.commission), "tax": raw_money(ZERO, trade.tax)},
        }
        self.fills.append(row)
        self.fills_hash = strategy_input_fingerprint({"prior": self.fills_hash, "fill": row})
        self.account_as_of = stamp
        self.witness.trade(row, candidate.session.day, price, fee)
        self.markers.append({"at": modeled.isoformat(), "kind": "ENTRY" if effect == "OPEN" else "EXIT",
                             "price": text(price), "label": effect, "signal_id": attempt["signal_id"],
                             "native_trade_id": row["native_trade_id"], "contract": self.contract})

    def handle_bar(self, _, bars) -> None:
        env = self.env
        at = local(env.calendar_dt)
        if next(self.visited, None) != at:
            raise BacktestError("PLUS_NATIVE_CALLBACK_MINUTE_COVERAGE_MISMATCH")
        source = self.packet.minutes[at]
        bar = bars[self.contract]
        if (
            env.trading_dt.date() != source.session.day or local(bar.datetime) != at
            or any(finite(getattr(bar, key), positive=True) != getattr(source, key)
                   for key in ("open", "high", "low", "close"))
            or finite(bar.volume) != source.volume
        ):
            raise BacktestError("PLUS_NATIVE_CALLBACK_BAR_MISMATCH")
        if self.outstanding is not None:
            order, attempt = self.outstanding
            if at.isoformat() != attempt["candidate_bar_end"]:
                raise BacktestError("PLUS_NATIVE_ORDER_EXPIRY_CLOCK_MISMATCH")
            if not order.is_final():
                env.broker.cancel_order(order)
                attempt["reason"] = "FIRST_CANDIDATE_EXPIRED"
            else:
                attempt["reason"] = attempt.get("candidate_guard", "NATIVE_" + order.status.name)
            self.outstanding = None
        self.advance(at, trading=True)
        if self.awaiting_submission is not None:
            action, payload, opening, attempt = self.awaiting_submission
            if at > opening:
                raise BacktestError("PLUS_NATIVE_ORDER_CALLBACK_MISSING")
            if at == opening:
                self.awaiting_submission = None
                self.submit(action, payload, opening, attempt)
        self.rows.append(source)
        if len(self.rows) == 5:
            self.pending = _bar_input(self.rows, self.packet, self.config, self.owner)
            self.rows.clear()

    def pre_settlement(self, _) -> None:
        day = self.env.trading_dt.date()
        facts = self.packet.days[day]
        clock = local(self.env.calendar_dt)
        self.advance(clock, trading=False)
        if self.outstanding is not None or self.awaiting_submission is not None:
            raise BacktestError("PLUS_SETTLEMENT_WITH_LIVE_ORDER")
        self.pre_settlement_account, _ = self.witness.account(self.account, day, facts.last_close,
                                                              self.rates[day]["margin"], settled=False)
        self.cost_data_source.begin_settlement(day, self.instrument)

    def post_settlement(self, _) -> None:
        day = self.env.trading_dt.date()
        clock = local(self.env.calendar_dt)
        facts = self.packet.days[day]
        if (clock.date() != day or clock.time() < time(15)
                or self.pre_settlement_account is None):
            raise BacktestError("PLUS_NATIVE_SETTLEMENT_CLOCK_MISMATCH")
        settlement_margin = self.costs.settlement_long_margin(day)
        raw, equity = self.witness.account(self.account, day, facts.settlement, settlement_margin, settled=True)
        self.settlements.append({"at": clock.isoformat(), "trading_day": day.isoformat(),
                                 "settlement_price": text(facts.settlement), "settlement_long_margin": text(settlement_margin),
                                 "before": self.pre_settlement_account, "after": raw})
        self.pre_settlement_account = None
        if day >= self.config.start:
            self.peak = max(self.peak, equity)
            self.equity.append({"at": clock.isoformat(), "trading_day": day.isoformat(),
                                "equity": text(equity), "drawdown": text(1 - equity / self.peak)})

    def result(self, native: dict) -> dict:
        if (
            not self.started or next(self.visited, None) is not None or self.rows or self.outstanding is not None
            or self.awaiting_submission is not None
            or [row["trading_day"] for row in self.equity] != self.evaluation_days
            or [row["trading_day"] for row in self.settlements] != [day.isoformat() for day in self.packet.days]
        ):
            raise BacktestError("PLUS_NATIVE_EXECUTION_TRACE_INCOMPLETE")
        if self.pending is not None:
            # The final completed bar may become available after the 15:00 settlement callback.
            # Its signal is still available for analysis, with no eligible execution candidate.
            self.advance(self.pending.available_at, trading=False)
        analysis = native.get("sys_analyser") if isinstance(native, dict) else None
        if not isinstance(analysis, dict) or "portfolio" not in analysis or "trades" not in analysis:
            raise BacktestError("PLUS_NATIVE_ANALYSER_OUTPUT_MISSING")
        portfolio = analysis["portfolio"]
        if len(portfolio) != len(self.settlements) or len(analysis["trades"]) != len(self.fills):
            raise BacktestError("PLUS_NATIVE_ANALYSER_TRACE_MISMATCH")
        for (day, row), settlement in zip(portfolio.iterrows(), self.settlements, strict=True):
            # sys_analyser is a rounded reporting projection. Settlement callbacks
            # retain and independently reconcile the original binary amounts.
            if day.date().isoformat() != settlement["trading_day"] or float(row["total_value"]) != round(
                float(settlement["after"]["native_equity"]["repr"]), 4
            ):
                raise BacktestError("PLUS_NATIVE_ANALYSER_TRACE_MISMATCH")
        for (_, row), fill in zip(analysis["trades"].iterrows(), self.fills, strict=True):
            if (str(row["exec_id"]), str(row["order_id"]), row["order_book_id"], int(row["last_quantity"])) != (
                fill["native_trade_id"], fill["native_order_id"], self.contract, 1,
            ):
                raise BacktestError("PLUS_NATIVE_ANALYSER_TRACE_MISMATCH")
        native_summary = {
            key: str(analysis["summary"][key])
            for key in ("total_value", "cash", "total_returns", "unit_net_value", "max_drawdown", "annualized_returns")
            if key in analysis.get("summary", {}) and isfinite(float(analysis["summary"][key]))
        }
        last_day = next(reversed(self.packet.days))
        terminal = self.witness.terminal(datetime.fromisoformat(self.equity[-1]["at"]),
                                         self.packet.days[last_day].settlement, expired=last_day == self.expiry)
        output = {
            "summary": {"metrics": metrics(self.equity, self.witness.trades, self.config.initial_capital),
                        "sample_type": self.config.sample_type, "qualification": "TRIAL",
                        "contract": self.contract, "currency": "CNY", "cost_basis": MONEY_POLICY},
            "equity": self.equity, "trades": self.witness.trades,
            "bars": self.bars, "markers": self.markers,
            "report": {
                "evaluation_trading_days": self.evaluation_days,
                "first_evaluation_session_open": self.initial_session.isoformat(),
                "evaluation_start_at": self.initial_session.isoformat(), "initial_position": "FLAT",
                "evaluation_initial_position": "FLAT", "evaluation_initial_equity": text(self.config.initial_capital),
                "terminal_position": terminal, "attempts": self.attempts, "native_fills": self.fills,
                "native_settlements": self.settlements, "benchmark": "cash",
                "native_analysis_source": "rqalpha-plus/sys_analyser", "native_analysis": native_summary,
                "native_analysis_scope": "configured_warmup_and_evaluation", "availability_policy": AVAILABILITY_POLICY,
                "money_policy": MONEY_POLICY, "account_binary_tolerance_cny": text(ACCOUNT_BINARY_TOLERANCE),
                "input_minute_count": len(self.packet.minutes),
                "dated_cost_profile": self.costs.snapshot(),
                "execution_delay_minutes": self.config.execution_delay_minutes,
            },
        }
        return output


def execute(config: dict, run_id: str, bundle: Path, expected_snapshot: dict | None,
            admit: Callable[[dict], None], *, cost_profile: Path | None = None) -> dict:
    """Authorize, freeze local inputs, and execute through the pinned Plus engine."""
    if (
        config["formula_version"] != NEWOW_TREND_D1_PAGE_V2.trend_band_formula
        or config["profile_id"] != NEWOW_TREND_D1_PAGE_V2.profile_id
    ):
        raise BacktestError("STRATEGY_FORMULA_OR_PROFILE_UNVERIFIED")
    native = NativeConfig.from_effective(config)
    packet = preflight(native, bundle)
    costs = DatedCosts.load(cost_profile, native.contract, packet.days)
    if expected_snapshot is not None and (
        expected_snapshot.get("data_revision") != packet.dataset_revision
        or expected_snapshot.get("input_sha256") != _input_identity(packet, costs)
        or expected_snapshot.get("cost_artifact_sha256") != costs.artifact_sha256
    ):
        raise BacktestError("PLUS_ORIGINAL_INPUT_UNREPRODUCIBLE")
    if not os.environ.get("RQSDK_LICENSE"):
        raise BacktestError("PLUS_LICENSE_NOT_CONFIGURED")

    # Importing Plus binds the installed Plus config and modules. No public user
    # config or alternate engine/backend is loaded.
    import rqalpha_plus
    from rqalpha import main
    from rqalpha.utils.functools import clear_all_cached_functions

    if rqalpha_plus.__version__ != packet.compatibility["rqalpha-plus"]:
        raise BacktestError("PLUS_ENGINE_VERSION_UNVERIFIED")
    channel = LicenseChannel()
    run = NativeRun(packet, native, run_id, admit, channel, costs)

    cfg = _config(native, packet)
    clear_all_cached_functions()
    try:
        with channel.guard():
            result = main.run(
                cfg, user_funcs={"init": run.checked(run.init), "handle_bar": run.checked(run.handle_bar)}
            )
    except BacktestError:
        raise
    except Exception:
        if run.error or channel.error:
            raise BacktestError(run.error or channel.error) from None
        if channel.blocked:
            raise BacktestError("PLUS_OFFLINE_TRADING_FACTS_UNAVAILABLE") from None
        if not channel.granted_transport:
            raise BacktestError("PLUS_LICENSE_SERVICE_UNREACHABLE") from None
        if not run.started:
            raise BacktestError("PLUS_LICENSE_OR_NATIVE_ADMISSION_UNVERIFIED") from None
        raise BacktestError("PLUS_NATIVE_EXECUTION_FAILED") from None
    packet.verify_unchanged()
    costs.verify_unchanged()
    with localcontext(MONEY_CONTEXT):
        return run.result(result)
