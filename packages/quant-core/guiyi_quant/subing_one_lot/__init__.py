"""Isolated JM research policy over the existing decision and execution engines.

This factory has no Runtime consumer. It never changes the imported account
module, an existing model run, or the meaning of historical profiles.
"""

from copy import deepcopy
from dataclasses import asdict
from datetime import timedelta
from decimal import Decimal as D
from types import MappingProxyType

from guiyi_quant.indicators.subing_conditions import EntryWindow, observe_entry
from guiyi_quant.subing_decision import (
    REGIME_PROFILE,
    _digest,
    _number,
    _wire,
    candidate_side,
    directional_frame,
)
from guiyi_quant.subing_demand_account_candidate import build_engine as build_base

VERSION = "subing_jm_one_lot_fixed2000_v1"
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
    executions, schedule, *, structures, execution_model="theoretical_open"
):
    if execution_model not in ("theoretical_open", "completed_close"):
        raise ValueError("ONE_LOT_EXECUTION_MODEL_INVALID")
    bars = (
        executions
        if isinstance(executions, dict)
        else {x.bar.bar_end: x for x in executions}
    )
    contracts = {x.bar.physical_contract for x in bars.values()}
    if not bars or len(contracts) != 1 or not next(iter(contracts)).startswith("JM"):
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
            "policy": dict(POLICY),
            "execution_model": execution_model,
        }
    )

    class Candidate(BaseCandidate):
        def __init__(self, contract, run_id, **kwargs):
            if (
                not contract.startswith("JM")
                or kwargs.get("research_profile") is not None
                or kwargs.get("risk_research_profile") is not None
                or kwargs.get("regime_research_profile") != REGIME_PROFILE
            ):
                raise ValueError("ONE_LOT_PROFILE_COMBINATION_INVALID")
            super().__init__(contract, run_id, **kwargs)
            self.version = VERSION
            self.slippage_ticks = 1
            self.trade_entry = None
            self.loss_streak = 0
            self.loss_pause_day = None
            self.loss_pause_at = None
            self.last_closed_net = None
            self.closed_trade_count = 0

        def state(self):
            return dict(
                super().state(),
                one_lot_policy=dict(POLICY),
                loss_streak=self.loss_streak,
                loss_pause_day=self.loss_pause_day,
                loss_pause_at=self.loss_pause_at,
                trade_entry=_wire(self.trade_entry),
                last_closed_net=_wire(self.last_closed_net),
                closed_trade_count=self.closed_trade_count,
            )

        def _ack(self, event, at):
            pending = deepcopy(self.pending)
            if pending and pending["kind"] == "ADD":
                raise ValueError("ONE_LOT_ADD_FORBIDDEN")
            trade = deepcopy(self.trade_entry)
            facts = None
            if event.get("status") == "FILLED":
                end = (
                    at + timedelta(minutes=1)
                    if execution_model == "theoretical_open"
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
                        or risk > D(POLICY["trade_loss_budget"])
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
                if self.loss_streak >= POLICY["loss_streak_trigger"]:
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
                    denied = risk is None or risk > D(POLICY["trade_loss_budget"])
                else:
                    denied = True
                if denied:
                    adjusted["admission"] = False
            # A one-lot ordinary reduction is a complete exit. Preserve the
            # original trigger set; this does not broaden the MACD definition.
            if (
                self.layers
                and view
                and (view["below_previous_low"] is True or view["high_death"] is True)
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
                row["conditions"]["one_lot_policy"] = dict(POLICY)
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
                version=VERSION,
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
                checkpoint["version"] != VERSION
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
            if self.live or self.at_open != (execution_model == "theoretical_open"):
                raise ValueError("ONE_LOT_OFFLINE_EXECUTION_ONLY")
            self.model.slippage_ticks = self.slippage_ticks
            self.inputs = []
            self.seen_inputs = {}
            self.failed = False

        def finance(self, mark, facts, side):
            result = super().finance(mark, facts, side)
            result["admission"] = result["admission"] and not self.layers
            result["round_loss"] = bool(
                self.layers
                and result["remaining_net"] <= -D(POLICY["trade_loss_budget"])
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
                if risk is None or risk > D(POLICY["trade_loss_budget"]):
                    result["admission"] = False
            return result

        def step(self, execution, technical, *, observed_at=None):
            if self.failed:
                raise ValueError("ONE_LOT_RESTORE_REQUIRED")
            source = bars.get(execution.bar.bar_end)
            if source is None or _wire(asdict(source)) != _wire(asdict(execution)):
                raise ValueError("ONE_LOT_ACCOUNT_INPUT_CHANGED")
            wire = _wire(dict(execution=asdict(execution), technical=technical))
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
                VERSION + "_" + execution_model + "_slip" + str(self.slippage_ticks)
            )
            result["research_policy"] = dict(POLICY)
            result["context_hash"] = context
            result["assumptions"] = result["assumptions"].replace(
                "capacity assumed up to 3 lots", "capacity assumed up to 1 lot"
            )
            return result

        def checkpoint(self):
            if self.failed:
                raise ValueError("ONE_LOT_RESTORE_REQUIRED")
            payload = dict(
                version=VERSION,
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
                checkpoint["version"] != VERSION
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
    module.INITIAL_CASH = D(POLICY["initial_cash"])
    module.DecisionModel = Candidate
    module.AccountEngine = Account
    return module, Candidate, context
