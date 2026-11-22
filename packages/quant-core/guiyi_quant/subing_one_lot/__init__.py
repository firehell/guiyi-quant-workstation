"""Isolated JM research policy over the existing decision and execution engines.

This factory has no Runtime consumer. It never changes the imported account
module, an existing model run, or the meaning of historical profiles.
"""

from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timedelta
from decimal import Decimal as D
from types import MappingProxyType

from guiyi_quant.trading_universe import TRADING_PRODUCTS
from guiyi_quant.indicators.subing_conditions import EntryWindow, observe_entry
from guiyi_quant.subing_decision import (
    REGIME_PROFILE,
    _digest,
    _number,
    _wire,
    candidate_side,
    directional_frame,
    direction_sign,
)
from guiyi_quant.subing_demand_account_candidate import build_engine as build_base

VERSION = "subing_jm_one_lot_fixed2000_v1"
HOUR_EXIT = "profitable_h1_ema21_exit_v1"
RANGE_EXIT = "trend_to_m30_range_close_v1"
RESEARCH_EXIT_PROFILES = (HOUR_EXIT, RANGE_EXIT)
POLICY = MappingProxyType(
    {
        "version": VERSION,
        "initial_cash": "1000000",
        "trade_loss_budget": "2000",
        "daily_loss_budget": "5000",
        "max_lots": 1,
        "loss_streak_trigger": 3,
        "planned_cost": "entry_slippage_plus_exit_slippage_plus_max_close_fee",
        "resume": "later_trading_day_same_direction_trend_fresh_qualified_window",
    }
)


PORTFOLIO_PRODUCTS = tuple("jm lc rb sa fg ma ec v pr ta ur sh sc cj".split())

# The 14-product identity remains decodeable only for historical research.
EXPANDED_PORTFOLIO_PRODUCTS = TRADING_PRODUCTS
PORTFOLIO_POLICY = MappingProxyType({
    **POLICY,
    "version": "subing_portfolio_one_lot_v1",
    "trade_loss_budget": "5000",
    "daily_loss_budget": "20000",
    "margin_fraction": "0.70",
})


def portfolio_policy(products):
    if products == PORTFOLIO_PRODUCTS:
        return dict(PORTFOLIO_POLICY)
    if products == EXPANDED_PORTFOLIO_PRODUCTS:
        return {**PORTFOLIO_POLICY, "version": "subing_portfolio_one_lot_v2", "products": list(products)}
    raise ValueError("PORTFOLIO_SCOPE_INVALID")


def planned_loss(entry, stop, side, facts, slippage_ticks):
    """A stop-trigger estimate, not a maximum guaranteed execution loss.

    Entry already includes its adverse slippage. Include one adverse exit
    slippage and the greater current close/close-today fee at that exit price.
    Future fees, gaps and liquidity remain unknown.
    """
    sign = D(1 if side == "LONG" else -1)
    if entry <= 0 or stop <= 0 or sign * (entry - stop) <= 0:
        return None
    exit_price = stop - sign * facts.tick_size * slippage_ticks
    if exit_price <= 0:
        return None
    close_fee = max(
        facts.fees.amount(k, exit_price, facts.multiplier)
        for k in ("close", "close_today")
    )
    return (
        sign * (entry - exit_price) * facts.multiplier
        + facts.fees.amount("open", entry, facts.multiplier)
        + close_fee
    )


def build_engine(
    executions, schedule, *, structures, execution_model="theoretical_open", portfolio=False,
    portfolio_products=PORTFOLIO_PRODUCTS, exit_profile=None, legacy_close_witness=False,
):
    policy = portfolio_policy(portfolio_products) if portfolio else POLICY
    if exit_profile is not None and exit_profile not in RESEARCH_EXIT_PROFILES:
        raise ValueError("ONE_LOT_EXIT_PROFILE_INVALID")
    if exit_profile:
        policy = {
            **policy,
            "version": f"{policy['version']}:{exit_profile}",
            "exit_profile": exit_profile,
        }
    version = policy["version"]
    products = portfolio_products if portfolio else ("jm",)
    if portfolio and execution_model != "completed_close":
        raise ValueError("PORTFOLIO_COMPLETED_CLOSE_REQUIRED")
    if execution_model not in ("theoretical_open", "completed_close"):
        raise ValueError("ONE_LOT_EXECUTION_MODEL_INVALID")
    if legacy_close_witness:
        if portfolio or execution_model != "theoretical_open":
            raise ValueError("ONE_LOT_LEGACY_WITNESS_INVALID")
        policy = {**policy, "version": f"{policy['version']}:legacy_close_witness_v1"}
        version = policy["version"]
    bars = (
        executions
        if isinstance(executions, dict)
        else {x.bar.bar_end: x for x in executions}
    )
    contracts = {x.bar.physical_contract for x in bars.values()}
    if not bars or len(contracts) != 1 or next(iter(contracts))[:-4].lower() not in products:
        raise ValueError("ONE_LOT_JM_ONLY")
    if not isinstance(structures, dict) or set(structures) != {
        at.isoformat() for at in bars
    }:
        raise ValueError("ONE_LOT_STRUCTURE_COVERAGE")
    module, BaseCandidate, base_context = build_base(
        bars, schedule, structures=structures
    )
    context = _digest(
        {
            "base_context": base_context,
            "policy": dict(policy),
            "execution_model": execution_model,
        }
    )

    class Candidate(BaseCandidate):
        supported_products = tuple(p.upper() for p in products)
        cross_product_regime = portfolio

        def __init__(self, contract, run_id, **kwargs):
            if (
                contract[:-4].lower() not in products
                or kwargs.get("research_profile") is not None
                or kwargs.get("risk_research_profile") is not None
                or kwargs.get("regime_research_profile") != REGIME_PROFILE
            ):
                raise ValueError("ONE_LOT_PROFILE_COMBINATION_INVALID")
            super().__init__(contract, run_id, **kwargs)
            self.version = version
            self.slippage_ticks = 1
            self.trade_entry = None
            self.loss_streak = 0
            self.loss_pause_day = None
            self.loss_pause_at = None
            self.last_closed_net = None
            self.closed_trade_count = 0
            self.hour_exit_since = None

        def state(self):
            state = dict(
                super().state(),
                one_lot_policy=dict(policy),
                loss_streak=self.loss_streak,
                loss_pause_day=self.loss_pause_day,
                loss_pause_at=self.loss_pause_at,
                trade_entry=_wire(self.trade_entry),
                last_closed_net=_wire(self.last_closed_net),
                closed_trade_count=self.closed_trade_count,
            )
            if exit_profile == HOUR_EXIT:
                state["hour_exit_since"] = _wire(self.hour_exit_since)
            return state

        def _exit_frame(self, frame):
            if self.hour_exit_since is None or frame is None:
                return frame
            return dict(frame, below_previous_low=False, below_ema=False)

        def _current_hour(self, at):
            hour = structures[at.isoformat()].get("hourly")
            if not hour:
                return None
            hour_at = datetime.fromisoformat(hour["at"])
            if hour_at.utcoffset() is None or hour_at > at:
                raise ValueError("ONE_LOT_H1_TIME_CONFLICT")
            if hour_at != at:
                return None
            close = _number(hour["close"], positive=True)
            ema = _number(hour["ema21"], nullable=True, positive=True)
            if close != bars[at].bar.close:
                raise ValueError("ONE_LOT_H1_CLOSE_CONFLICT")
            if ema is None and self.hour_exit_since is not None:
                raise ValueError("ONE_LOT_H1_EMA_UNAVAILABLE_AFTER_HANDOFF")
            return (close, ema, hour["direction"]) if ema is not None else None

        def _ack(self, event, at):
            pending = deepcopy(self.pending)
            if pending and pending["kind"] == "ADD":
                raise ValueError("ONE_LOT_ADD_FORBIDDEN")
            trade = deepcopy(self.trade_entry)
            facts = None
            if event.get("status") == "FILLED":
                end = (
                    at + timedelta(minutes=1)
                    if execution_model == "theoretical_open" and not (
                        legacy_close_witness and pending and pending["kind"] == "CLOSE"
                    )
                    else at
                )
                if end not in bars:
                    raise ValueError("ONE_LOT_FILL_SOURCE_MISSING")
                facts = bars[end].facts
                if pending and pending["kind"] == "OPEN":
                    risk = planned_loss(
                        _number(event["price"], positive=True),
                        pending["initial_stop"],
                        pending["side"],
                        facts,
                        self.slippage_ticks,
                    )
                    if (
                        self.layers
                        or risk is None
                        or risk > D(policy["trade_loss_budget"])
                    ):
                        raise ValueError("ONE_LOT_FILL_RISK_INVALID")
            actions = super()._ack(event, at)
            if event["status"] == "FILLED" and pending["kind"] == "OPEN":
                price = D(event["price"])
                self.trade_entry = dict(
                    price=price,
                    side=pending["side"],
                    trading_day=facts.trading_day,
                    open_fee=facts.fees.amount("open", price, facts.multiplier),
                )
            elif (
                event["status"] == "FILLED"
                and pending["kind"] == "CLOSE"
                and not self.layers
            ):
                if trade is None:
                    raise ValueError("ONE_LOT_TRADE_SOURCE_MISSING")
                price = D(event["price"])
                fee_kind = (
                    "close_today"
                    if trade["trading_day"] == facts.trading_day
                    else "close"
                )
                sign = D(1 if trade["side"] == "LONG" else -1)
                net = (
                    sign * (price - trade["price"]) * facts.multiplier
                    - trade["open_fee"]
                    - facts.fees.amount(fee_kind, price, facts.multiplier)
                )
                self.last_closed_net = net
                self.closed_trade_count += 1
                self.loss_streak = self.loss_streak + 1 if net < 0 else 0
                self.trade_entry = None
                self.hour_exit_since = None
                if self.loss_streak >= policy["loss_streak_trigger"]:
                    self.loss_pause_day = facts.trading_day.isoformat()
                    self.loss_pause_at = at
                    self.windows = {
                        side: EntryWindow(self.contract, w.last_end)
                        for side, w in self.windows.items()
                    }
            return actions

        def _observe(self, event, at):
            adjusted = deepcopy(event)
            raw = event["m30"]
            side = self.side or candidate_side(raw or self.latest_frame)
            view = directional_frame(raw, side)
            hour = self._current_hour(at) if exit_profile == HOUR_EXIT else None
            hour_distance = (
                direction_sign(side) * (hour[0] - hour[1])
                if hour and self.layers else None
            )
            if (
                self.hour_exit_since is not None
                and at > self.hour_exit_since
                and hour_distance is not None
                and hour_distance < 0
                and not (self.pending or self.clear_reasons or self.exit_layers)
            ):
                self.clear_reasons.append("H1_EMA21_CLEAR")
            if (
                exit_profile == RANGE_EXIT
                and self.layers
                and self.regime == ("TREND_UP" if side == "LONG" else "TREND_DOWN")
                and raw is not None
                and raw["regime"] == "RANGE"
                and not (self.pending or self.clear_reasons or self.exit_layers)
            ):
                self.clear_reasons.append("M30_TREND_TO_RANGE_CLEAR")
            risk = None
            denied = False
            if not self.layers and not self.pending and view is not None:
                ema = _number(view["ema21"], nullable=True, positive=True)
                extreme = _number(view["low"], nullable=True, positive=True)
                if ema is not None and extreme is not None:
                    stop = (
                        min(ema, extreme) - self.stop_buffer
                        if side == "LONG"
                        else max(ema, extreme) + self.stop_buffer
                    )
                    facts = bars[at].facts
                    sign = D(1 if side == "LONG" else -1)
                    entry = (
                        D(event["close"]) + sign * facts.tick_size * self.slippage_ticks
                    )
                    risk = planned_loss(entry, stop, side, facts, self.slippage_ticks)
                    denied = risk is None or risk > D(policy["trade_loss_budget"])
                else:
                    denied = True
                if denied:
                    adjusted["admission"] = False
            # A one-lot ordinary reduction is a complete exit. Preserve the
            # original trigger set; this does not broaden the MACD definition.
            exit_view = self._exit_frame(view)
            if (
                self.layers
                and exit_view
                and (exit_view["below_previous_low"] is True or exit_view["high_death"] is True)
            ):
                self.clear_reasons = list(
                    dict.fromkeys(self.clear_reasons + ["ONE_LOT_ORDINARY_EXIT"])
                )
            if self.layers:
                adjusted["admission"] = False

            pause_active = self.loss_pause_day is not None
            resume_attempt = False
            preview = None
            if pause_active and view is not None:
                daily = (
                    event["daily_direction"]
                    if side == "LONG"
                    else {"UP": "DOWN", "DOWN": "UP"}.get(
                        event["daily_direction"], event["daily_direction"]
                    )
                )
                _, preview = observe_entry(
                    self.windows[side],
                    contract=self.contract,
                    bar_end=at,
                    near_zero_golden=view["near_zero_golden"],
                    daily_direction=daily,
                    minute_angle=_number(view["minute_angle"], nullable=True),
                    above_ema=view["above_ema"],
                    volume_effective=view["volume_effective"],
                    max_age=self.window_age,
                )
                source = preview["window"]["source_end"]
                regime = raw.get("regime", self.regime)
                structure = structures.get(at.isoformat(), {})
                can_resume = (
                    event["trading_day"] > self.loss_pause_day
                    and preview["met"] is True
                    and source is not None
                    and source > self.loss_pause_at
                    and regime == ("TREND_UP" if side == "LONG" else "TREND_DOWN")
                    and structure.get("phase") != "BREAK_PENDING"
                    and adjusted["admission"] is True
                    and event["reconciled"] is True
                    and event["round_loss"] is False
                    and event["day_loss"] is False
                    and not self.day_halted
                    and not event["day_end_window"]
                    and not self.layers
                    and not self.pending
                    and not self.clear_reasons
                )
                if can_resume:
                    # The shared model must still prove ALL original technical
                    # and execution-admission conditions. Do not clear a latch
                    # merely because this preliminary gate looks eligible.
                    resume_attempt = True
                    pause_active = False
            if pause_active:
                adjusted["admission"] = False
            actions = super()._observe(adjusted, at)
            if (
                exit_profile == HOUR_EXIT
                and self.hour_exit_since is None
                and self.layers
                and at > self.round_started_at
                and not (self.pending or self.clear_reasons or self.exit_layers)
                and event["reconciled"] is True
                and event["round_loss"] is False
                and event["day_loss"] is False
                and hour_distance is not None
                and hour_distance > 0
                and hour[2] == ("UP" if side == "LONG" else "DOWN")
            ):
                net = _number(event["remaining_net"], nullable=True)
                technical_risk = self.risk_distance * bars[at].facts.multiplier
                if net is not None and technical_risk > 0 and net >= technical_risk:
                    self.hour_exit_since = at
            if resume_attempt:
                if any(action.get("kind") == "OPEN" for action in actions):
                    self.loss_pause_day = None
                    self.loss_pause_at = None
                    self.loss_streak = 0
                else:
                    pause_active = True
            if pause_active:
                # Keep the original 0..5 clock while a later-day opportunity
                # waits only for a confirmed environment. Same-day crosses do
                # not become next-day admission tickets.
                if event["trading_day"] <= self.loss_pause_day:
                    self.windows = {
                        s: EntryWindow(self.contract, w.last_end)
                        for s, w in self.windows.items()
                    }
                elif (
                    preview
                    and preview["met"] is True
                    and not denied
                    and event["admission"] is True
                    and any(
                        action.get("kind") == "REJECT"
                        and action.get("opportunity") == "OPEN"
                        and set(action.get("reasons", []))
                        == {"ADMISSION_OR_RISK_NOT_PROVEN"}
                        for action in actions
                    )
                ):
                    w = preview["window"]
                    if w["source_end"] and w["age"] < self.window_age:
                        self.windows[side] = EntryWindow(
                            self.contract, at, w["source_end"], w["age"]
                        )
            for action in actions:
                if (
                    action.get("kind") == "REJECT"
                    and action.get("opportunity") == "OPEN"
                ):
                    if denied:
                        action["reasons"].append("PLANNED_STOP_RISK_OVER_BUDGET")
                    if pause_active:
                        action["reasons"].append("CONSECUTIVE_LOSS_PAUSE")
            if self.chain:
                row = self.chain[-1]
                row["conditions"]["planned_loss"] = None if risk is None else str(risk)
                row["conditions"]["one_lot_policy"] = dict(policy)
                row["conditions"]["loss_pause_day"] = self.loss_pause_day
                row["actions"] = _wire(actions)
                row["position"] = self.state()
                extra = (["PLANNED_STOP_RISK_OVER_BUDGET"] if denied else []) + (
                    ["CONSECUTIVE_LOSS_PAUSE"] if pause_active else []
                )
                row["blocking_reasons"] = list(
                    dict.fromkeys(row["blocking_reasons"] + extra)
                )
                if pause_active and not row["trigger_reasons"] and not self.pending:
                    row.update(
                        demand="WAIT",
                        reason="CONSECUTIVE_LOSS_PAUSE",
                        next_wait="LATER_TRADING_DAY_CLEAR_TREND_FRESH_ENTRY",
                    )
            return actions

        def checkpoint(self):
            payload = dict(
                version=version,
                contract=self.contract,
                run_id=self.run_id,
                context_hash=context,
                slippage_ticks=self.slippage_ticks,
                events=deepcopy(self.events),
            )
            return dict(payload, sha256=_digest(payload))

        @classmethod
        def restore(cls, checkpoint):
            payload = {k: v for k, v in checkpoint.items() if k != "sha256"}
            if (
                checkpoint["version"] != version
                or checkpoint["context_hash"] != context
                or _digest(payload) != checkpoint["sha256"]
                or type(checkpoint.get("slippage_ticks")) is not int
                or checkpoint["slippage_ticks"] not in (1, 2, 3)
            ):
                raise ValueError("CHECKPOINT_INVALID")
            obj = cls(
                checkpoint["contract"],
                checkpoint["run_id"],
                regime_research_profile=REGIME_PROFILE,
            )
            obj.slippage_ticks = checkpoint["slippage_ticks"]
            for event in checkpoint["events"]:
                obj.apply(event)
            return obj

    BaseAccount = module.AccountEngine

    class Account(BaseAccount):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            if self.live != portfolio or self.at_open != (execution_model == "theoretical_open"):
                raise ValueError("ONE_LOT_OFFLINE_EXECUTION_ONLY")
            self.model.slippage_ticks = self.slippage_ticks
            self.inputs = []
            self.seen_inputs = {}
            self.failed = False
            self.portfolio_finance = None

        def _fill_on_open(self, pending):
            if legacy_close_witness and pending and pending["kind"] == "CLOSE":
                return False
            return super()._fill_on_open(pending)

        def finance(self, mark, facts, side):
            result = super().finance(mark, facts, side)
            result["admission"] = result["admission"] and not self.layers
            result["round_loss"] = bool(
                self.layers
                and result["remaining_net"] <= -D(policy["trade_loss_budget"])
            )
            pending = self.model.pending
            if pending and pending["kind"] == "OPEN":
                sign = D(1 if side == "LONG" else -1)
                risk = planned_loss(
                    mark + sign * facts.tick_size * self.slippage_ticks,
                    pending["initial_stop"],
                    side,
                    facts,
                    self.slippage_ticks,
                )
                result["planned_entry_loss"] = risk
                if risk is None or risk > D(policy["trade_loss_budget"]):
                    result["admission"] = False
            if portfolio:
                if self.portfolio_finance is None:
                    raise ValueError("PORTFOLIO_FINANCE_REQUIRED")
                admission, day_loss = self.portfolio_finance(self, mark, facts, side)
                result["admission"] = admission and not self.layers and (
                    pending is None or pending["kind"] != "OPEN" or
                    result.get("planned_entry_loss") is not None and
                    result["planned_entry_loss"] <= D(policy["trade_loss_budget"])
                )
                result["day_loss"] = day_loss
            return result

        def step(self, execution, technical, *, observed_at=None):
            if self.failed:
                raise ValueError("ONE_LOT_RESTORE_REQUIRED")
            if exit_profile and self.live and (
                observed_at != execution.bar.bar_end
                or execution.bar.confirmed_at != execution.bar.bar_end
            ):
                raise ValueError("ONE_LOT_EXIT_RESEARCH_REQUIRES_BAR_END_KNOWLEDGE")
            source = bars.get(execution.bar.bar_end)
            if source is None or _wire(asdict(source)) != _wire(asdict(execution)):
                raise ValueError("ONE_LOT_ACCOUNT_INPUT_CHANGED")
            wire = _wire(dict(execution=asdict(execution), technical=technical))
            if portfolio:
                wire["observed_at"] = _wire(observed_at)
            event_id = technical["event_id"]
            fingerprint = _digest(wire)
            if event_id in self.seen_inputs:
                if self.seen_inputs[event_id] != fingerprint:
                    raise ValueError("ONE_LOT_INPUT_CONFLICT")
                return False
            before = len(self.closed_rounds)
            try:
                super().step(execution, technical, observed_at=observed_at)
                if (
                    len(self.layers) > 1
                    or len(self.fills)
                    and self.fills[-1]["action"] == "ADD"
                ):
                    raise ValueError("ONE_LOT_POSITION_VIOLATION")
                if (
                    len(self.closed_rounds) > before
                    and D(self.closed_rounds[-1]["net_pnl"])
                    != self.model.last_closed_net
                ):
                    raise ValueError("ONE_LOT_CLOSED_NET_RECONCILIATION")
            except Exception:
                self.failed = True
                raise
            self.inputs.append(wire)
            self.seen_inputs[event_id] = fingerprint
            return True

        def snapshot(self, **kwargs):
            result = super().snapshot(**kwargs)
            result["execution_engine_version"] = result["version"]
            result["version"] = (
                version + "_" + execution_model + "_slip" + str(self.slippage_ticks)
            )
            result["research_policy"] = dict(policy)
            result["context_hash"] = context
            result["assumptions"] = result["assumptions"].replace(
                "capacity assumed up to 3 lots", "capacity assumed up to 1 lot"
            )
            if legacy_close_witness:
                result["assumptions"] = (
                    "Development witness: theoretical entry; next executable "
                    "completed 1m exit with adverse slippage; no terminal liquidation"
                )
            return result

        def checkpoint(self):
            if portfolio:
                raise ValueError("PORTFOLIO_REPLAY_REQUIRED")
            if self.failed:
                raise ValueError("ONE_LOT_RESTORE_REQUIRED")
            payload = dict(
                version=version,
                context_hash=context,
                contract=self.contract,
                run_id=self.run_id,
                slippage_ticks=self.slippage_ticks,
                inputs=deepcopy(self.inputs),
                state_hash=_digest(self.snapshot()),
            )
            return dict(payload, sha256=_digest(payload))

        @classmethod
        def restore(cls, checkpoint):
            payload = {k: v for k, v in checkpoint.items() if k != "sha256"}
            if (
                checkpoint["version"] != version
                or checkpoint["context_hash"] != context
                or _digest(payload) != checkpoint["sha256"]
            ):
                raise ValueError("ONE_LOT_ACCOUNT_CHECKPOINT_INVALID")
            first = next(iter(bars.values()))
            obj = cls(
                checkpoint["contract"],
                "jm",
                first.facts.multiplier,
                checkpoint["run_id"],
                checkpoint["slippage_ticks"],
                execution_model,
                regime_research_profile=REGIME_PROFILE,
            )
            for wire in checkpoint["inputs"]:
                # Execution identity and facts are bound by the full context;
                # use that source and compare its entire serialized input.
                at = __import__("datetime").datetime.fromisoformat(
                    wire["execution"]["bar"]["bar_end"]
                )
                source = bars[at]
                if _wire(asdict(source)) != wire["execution"]:
                    raise ValueError("ONE_LOT_ACCOUNT_INPUT_CHANGED")
                obj.step(source, wire["technical"])
            if _digest(obj.snapshot()) != checkpoint["state_hash"]:
                raise ValueError("ONE_LOT_ACCOUNT_REPLAY_CONFLICT")
            return obj

    # Only this already-isolated module gets policy overrides. Imported account
    # globals and the continuously running development model are untouched.
    module.INITIAL_CASH = D(policy["initial_cash"])
    module.DecisionModel = Candidate
    module.AccountEngine = Account
    return module, Candidate, context
