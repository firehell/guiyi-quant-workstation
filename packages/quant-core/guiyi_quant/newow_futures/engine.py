"""Causal, costed historical model; never sends or persists an order."""
from __future__ import annotations

from bisect import bisect_left
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from decimal import Context, Decimal, ROUND_HALF_EVEN, localcontext
from hashlib import sha256
from typing import Mapping, Sequence

from .account import Account
from .contracts import Bar, Decision, ExecutionBar, Position, Profile, Variant
from .features import PreparedFeatures, prepare_features
from .reference import empty_reference, feature_stream, higher_at, run_reference
from .strategy import evaluate
from .curve import CurveRecorder

D = Decimal


@dataclass(frozen=True)
class Pending:
    action: str
    side: int
    reason: str
    at: datetime
    position: Position
    requested_qty: int


def _blocked(status: str, reference: dict | None = None) -> dict:
    ref = reference or empty_reference(status)
    return {"summary": {"status": status, "initial_cash": "100000", "final_equity": None,
                        "account_return_pct": None, "max_drawdown_pct": None, "total_fees": None,
                        "closed_trades": 0, "ending_qty": 0, "annual_eligible": False},
            "reference": {k: v for k, v in ref.items() if k != "chart"}, "chart": ref.get("chart", {"bars": [], "frames": []}),
            "decisions": [], "fills": [], "trades": [], "equity": [], "diagnostics": {"reason": status}}


def _stress(execution: ExecutionBar, scenario: str) -> ExecutionBar:
    if scenario != "double_commission":
        return execution
    f = execution.facts
    fees = replace(f.fees, open_rate=f.fees.open_rate * 2, open_per_contract=f.fees.open_per_contract * 2,
                   close_rate=f.fees.close_rate * 2, close_per_contract=f.fees.close_per_contract * 2,
                   close_today_rate=f.fees.close_today_rate * 2,
                   close_today_per_contract=f.fees.close_today_per_contract * 2)
    return replace(execution, facts=replace(f, fees=fees))


def run_research(bars_by_frequency: Mapping[str, Sequence[Bar]], execution_bars: Sequence[ExecutionBar], *,
                 profile: Profile, since: date, through: date, scenario: str = "baseline",
                 prepared: PreparedFeatures | None = None, reference: dict | None = None,
                 ticks: Mapping[tuple[str, date], Decimal] | None = None) -> dict:
    with localcontext(Context(prec=28, rounding=ROUND_HALF_EVEN)):
        return _run(bars_by_frequency, execution_bars, profile=profile, since=since, through=through,
                    scenario=scenario, prepared=prepared, reference=reference, ticks=ticks)


def _run(bars_by_frequency, execution_bars, *, profile, since, through, scenario, prepared, reference, ticks):
    if scenario not in ("baseline", "double_commission", "double_slippage") or since > through:
        raise ValueError("FUTURES_RESEARCH_QUERY_INVALID")
    if profile.variant == Variant.TEST3 and profile.frequency == "1w":
        return _blocked("NOT_APPLICABLE", reference)
    executions = tuple(execution_bars)
    if not executions or not bars_by_frequency.get(profile.frequency):
        return _blocked("EXECUTION_FACTS_MISSING" if bars_by_frequency.get(profile.frequency) else "DATA_INSUFFICIENT", reference)
    if any(b.bar.bar_end <= a.bar.bar_end for a, b in zip(executions, executions[1:])):
        raise ValueError("FUTURES_EXECUTION_ORDER_INVALID")
    if any(not since <= x.bar.trading_day <= through or not x.bar.observation_eligible for x in executions):
        raise ValueError("FUTURES_EXECUTION_WINDOW_INVALID")
    if any(x.bar.confirmed_at != x.bar.bar_end for x in executions):
        raise ValueError("FUTURES_EXECUTION_CLOCK_INVALID")
    if len({x.bar.product for x in executions}) != 1:
        raise ValueError("FUTURES_EXECUTION_PRODUCT_CONFLICT")
    prepared = prepared or prepare_features(bars_by_frequency)
    features = feature_stream(prepared, profile.frequency, bars_by_frequency[profile.frequency])
    features = tuple(f for f in features if since <= f.bar.trading_day <= through)
    if not features:
        return _blocked("DATA_INSUFFICIENT", reference)
    ticks = ticks or {(x.bar.physical_contract, x.bar.trading_day): x.facts.tick_size for x in executions}
    reference = reference or run_reference(profile, bars_by_frequency, tuple(x.bar for x in executions),
                                           prepared=prepared, ticks=ticks)
    account = Account()
    position: Position | None = None
    pending: Pending | None = None
    owner = None
    day: date | None = None
    day_start = account.cash
    daily_halt = False
    last_mark = None
    last_facts = None
    cooldown: datetime | None = None
    records: list[dict] = []
    equity = CurveRecorder()
    peak = account.cash
    drawdown = D(0)
    status = "COMPLETED"
    last_reject = None
    ready_count = 0
    i = j = 0
    slip = 2 if scenario == "double_slippage" else 1
    ends = tuple(x.bar.bar_end for x in executions)

    def record(at, action, reason, side=0, **extra):
        records.append({"decision_id": sha256(f"{profile.profile_id}|{at}|{action}|{len(records)}".encode()).hexdigest(),
                        "at": at.isoformat(), "bar_end": at.isoformat(), "action": action,
                        "reason": reason, "side": "LONG" if side > 0 else "SHORT" if side < 0 else "FLAT",
                        "holding_frequency": position.holding_frequency if position else None, **extra})

    def queue(at, action, reason, pos):
        nonlocal pending
        if pending and pending.action == action and pending.reason == reason:
            return
        if pending:
            record(at, "CANCEL", "SUPERSEDED_BY_" + action, pending.side)
        quantity = (account.open_quantity(pos.side, bar.close + pos.side * slip * facts.tick_size,
                                          pos.stop, facts, add=action == "ADD", slippage=slip)
                    if action in ("ENTER", "ADD") else account.reduce_quantity() if action == "REDUCE" else account.qty)
        if quantity <= 0 and action in ("ENTER", "ADD"):
            pending = None
            record(at, "REJECT", "MIN_LOT_BUDGET", pos.side)
            return
        pending = Pending(action, pos.side, reason, at, pos, quantity)
        record(at, action, reason, pos.side, effective_after=at.isoformat(), requested_qty=quantity)

    def interrupted(reason):
        if account.qty and position is not None:
            account.closed_trades.append({
                "trade_id": sha256(f"{account.contract}|{account.round_id}|interrupted".encode()).hexdigest(),
                "side": "LONG" if account.side > 0 else "SHORT", "physical_contract": account.contract,
                "entry_at": account.round_entry_at.isoformat(), "exit_at": None,
                "entry_price": str(account.round_entry_price), "exit_price": None,
                "qty": account.qty, "net_pnl": None, "status": reason,
                "holding_frequency": position.holding_frequency, "added": account.adds > 0,
                "overnight": account.round_entry_day != day,
            })

    while i < len(executions):
        execution = _stress(executions[i], scenario)
        bar, facts = execution.bar, execution.facts
        start = bar.bar_end - timedelta(minutes=1)
        if owner is not None and bar.owner != owner:
            if position is not None or pending is not None or account.qty:
                status = "ROLLOVER_INTERRUPTED"
                interrupted(status)
                record(bar.bar_end, "INTERRUPT", status, account.side)
                pending = None
                break
            cooldown = None
        owner = bar.owner
        if day != bar.trading_day:
            day = bar.trading_day
            day_start = account.equity(last_mark, last_facts) if account.qty and last_mark is not None else account.cash
            if not account.qty and pending is None:
                daily_halt = False
        late = (profile.frequency.endswith("m") and bar.session_close_at is not None
                and start >= bar.session_close_at - timedelta(minutes=2))
        if pending is not None and start > pending.at:
            intent = pending
            if late and intent.action in ("ENTER", "ADD"):
                record(start, "CANCEL", "DAY_END_OPEN_PROHIBITED", intent.side)
                pending = None
            else:
                buy = (intent.side > 0) if intent.action in ("ENTER", "ADD") else (intent.side < 0)
                price = bar.open + (1 if buy else -1) * slip * facts.tick_size
                rejection = ("ZERO_VOLUME" if bar.volume <= 0 else
                             "LIMIT_BLOCKED" if (buy and (bar.open >= facts.limit_up or price > facts.limit_up))
                             or (not buy and (bar.open <= facts.limit_down or price < facts.limit_down)) else
                             "NONPOSITIVE_FILL" if price <= 0 else None)
                if rejection:
                    if rejection != last_reject:
                        record(start, "UNFILLED", rejection, intent.side)
                    last_reject = rejection
                elif intent.action in ("ENTER", "ADD"):
                    add = intent.action == "ADD"
                    stop = (position.stop if position is not None and add else intent.position.stop)
                    add_profitable = (not add or (position is not None
                        and position.side * (price - position.entry) >= (account.adds + 1) * position.r
                        and account.equity(price, facts) - account.cash
                            > account.qty * account.close_cost_per_unit(price, facts, slippage=slip) * facts.multiplier))
                    quantity = 0 if daily_halt or not add_profitable else min(intent.requested_qty,
                        account.open_quantity(intent.side, price, stop, facts, add=add, slippage=slip))
                    if quantity <= 0:
                        record(start, "REJECT", "DAILY_HALT" if daily_halt else "ADD_NOT_PROFITABLE" if not add_profitable else "MIN_LOT_BUDGET", intent.side)
                    else:
                        account.open(intent.side, quantity, price, facts, start, stop,
                                     action=intent.action, slippage=slip)
                        account.fills[-1].update(decision_at=intent.at.isoformat(), fill_at=start.isoformat())
                        position = (replace(intent.position, entry=price, r=abs(price - intent.position.initial_stop),
                                            entry_at=start, stage_at=start, favorable_close=price)
                                    if not add else replace(position, adds=account.adds))
                    pending = None
                    last_reject = None
                else:
                    quantity = min(intent.requested_qty, account.reduce_quantity()) if intent.action == "REDUCE" else account.qty
                    if quantity <= 0:
                        record(start, "WAIT", "MIN_LOT_NOT_DIVISIBLE", intent.side)
                    else:
                        holding = position.holding_frequency
                        account.close(quantity, price, facts, start, reason=intent.reason, reduce=intent.action == "REDUCE")
                        account.fills[-1].update(decision_at=intent.at.isoformat(), fill_at=start.isoformat(), holding_frequency=holding)
                        if account.qty:
                            position = replace(position, reduced=True)
                        else:
                            position = None
                            cooldown = start
                            account.closed_trades[-1]["holding_frequency"] = holding
                    pending = None
                    last_reject = None
        mark_equity = account.equity(bar.close, facts)
        last_mark, last_facts = bar.close, facts
        peak = max(peak, mark_equity)
        drawdown = max(drawdown, (peak - mark_equity) / peak * 100)
        point = {"at": bar.bar_end.isoformat(), "value": str(mark_equity), "equity": str(mark_equity),
                 "physical_contract": bar.physical_contract}
        equity.add((bar.trading_day, bar.owner), point)
        if mark_equity <= day_start * D(".98") or (account.qty and account.margin(bar.close, facts) > mark_equity):
            daily_halt = True
            if position is not None:
                queue(bar.bar_end, "CLOSE", "DAILY_RISK_HALT", position)
            elif pending is not None:
                record(bar.bar_end, "CANCEL", "DAILY_RISK_HALT", pending.side)
                pending = None
        elif position is not None and (bar.close - position.stop) * position.side <= 0:
            queue(bar.bar_end, "CLOSE", "PROTECTIVE_CLOSE", position)
        elif (position is not None and profile.frequency.endswith("m") and bar.session_close_at is not None
              and bar.bar_end >= bar.session_close_at - timedelta(minutes=2) and not position.overnight_eligible):
            queue(bar.bar_end, "CLOSE", "DAY_ONLY_CLOSE", position)
        while j < len(features) and features[j].bar.confirmed_at <= bar.bar_end:
            base = features[j]
            j += 1
            if base.bar.owner != bar.owner:
                continue
            if position is None and cooldown is not None:
                if base.bar.bar_end <= cooldown:
                    continue
                cooldown = None
                record(base.bar.confirmed_at, "WAIT", "COOLDOWN")
                continue
            decision: Decision = evaluate(profile, base, higher_at(prepared, base), position,
                                          tick=facts.tick_size,
                                          close_cost_per_unit=account.close_cost_per_unit(base.bar.close, facts, slippage=slip))
            if decision.reason != "INPUT_UNAVAILABLE":
                ready_count += 1
            if pending is not None and pending.action == "ENTER" and (
                    decision.action != "ENTER" or decision.side != pending.side):
                record(base.bar.confirmed_at, "CANCEL", "ENTRY_NO_LONGER_VALID", pending.side)
                pending = None
            if decision.reason == "INPUT_UNAVAILABLE" and position is not None:
                status = "DATA_INTERRUPTED"
                interrupted(status)
                pending = None
                break
            if pending is not None and pending.action == "CLOSE":
                continue
            position = decision.position if account.qty else position
            if position is not None:
                account.tighten(position.stop)
            if pending is not None and pending.action == "REDUCE" and decision.action != "CLOSE":
                continue
            base_late = (profile.frequency.endswith("m") and base.bar.session_close_at is not None
                         and base.bar.confirmed_at >= base.bar.session_close_at - timedelta(minutes=2))
            if decision.action == "ENTER":
                if daily_halt or base_late:
                    record(base.bar.confirmed_at, "REJECT", "DAILY_HALT" if daily_halt else "DAY_END_OPEN_PROHIBITED", decision.side)
                elif pending is None:
                    queue(base.bar.confirmed_at, "ENTER", decision.reason, decision.position)
            elif decision.action == "CLOSE":
                queue(base.bar.confirmed_at, "CLOSE", decision.reason, position)
            elif position is not None and not position.overnight_eligible and account.round_entry_day != day:
                queue(base.bar.confirmed_at, "CLOSE", "OVERNIGHT_ELIGIBILITY_LOST", position)
            elif decision.action == "REDUCE":
                if account.reduce_quantity() == 0:
                    record(base.bar.confirmed_at, "WAIT", "MIN_LOT_NOT_DIVISIBLE", position.side)
                else:
                    queue(base.bar.confirmed_at, "REDUCE", decision.reason, position)
            elif decision.action == "ADD" and not daily_halt and not base_late and pending is None:
                queue(base.bar.confirmed_at, "ADD", decision.reason, position)
            elif decision.upgraded:
                record(base.bar.confirmed_at, "UPGRADE", "HOLDING_PERIOD_UPGRADED", position.side)
        if status == "DATA_INTERRUPTED":
            break
        i += 1
        if position is None and pending is None and j < len(features):
            i = max(i, bisect_left(ends, features[j].bar.confirmed_at, lo=i))
        elif position is None and pending is None and j >= len(features):
            break
    if status == "COMPLETED" and ready_count == 0:
        status = "DATA_INSUFFICIENT"
    if status == "COMPLETED" and pending is not None:
        status = "PENDING_UNFILLED"
    if status in ("COMPLETED", "PENDING_UNFILLED") and not account.fills and any(r["reason"] == "MIN_LOT_BUDGET" for r in records):
        status = "INSUFFICIENT_CAPITAL"
    if account.qty and position is not None and status not in ("ROLLOVER_INTERRUPTED", "DATA_INTERRUPTED"):
        account.closed_trades.append({"trade_id": sha256(f"{account.contract}|{account.round_id}|open".encode()).hexdigest(),
                                     "side": "LONG" if account.side > 0 else "SHORT", "physical_contract": account.contract,
                                     "entry_at": account.round_entry_at.isoformat(), "exit_at": None,
                                     "entry_price": str(account.round_entry_price), "exit_price": None,
                                     "qty": account.qty, "net_pnl": None, "status": "OPEN",
                                     "holding_frequency": position.holding_frequency, "added": account.adds > 0,
                                     "overnight": account.round_entry_day != day})
    complete = status not in ("ROLLOVER_INTERRUPTED", "DATA_INTERRUPTED", "DATA_INSUFFICIENT")
    final = account.equity(last_mark, last_facts) if last_mark is not None else account.cash
    summary = {"status": status, "initial_cash": "100000", "final_equity": str(final) if complete else None,
               "account_return_pct": str((final / account.initial_cash - 1) * 100) if complete else None,
               "max_drawdown_pct": str(drawdown), "total_fees": str(account.total_fees),
               "closed_trades": sum(t["status"] == "CLOSED" for t in account.closed_trades),
               "ending_qty": account.side * account.qty, "annual_eligible": status == "COMPLETED" and pending is None,
               "ending_cash": str(account.cash), "pending_action": pending.action if pending else None}
    attribution = {}
    for key in ("side", "holding_frequency", "added", "overnight"):
        grouped = {}
        for trade in account.closed_trades:
            if trade["status"] != "CLOSED":
                continue
            name = str(trade.get(key))
            group = grouped.setdefault(name, {"closed_trades": 0, "net_pnl": D(0)})
            group["closed_trades"] += 1
            group["net_pnl"] += D(trade["net_pnl"])
        attribution[key] = {name: {**value, "net_pnl": str(value["net_pnl"])} for name, value in grouped.items()}
    return {"summary": summary, "reference": {k: v for k, v in reference.items() if k != "chart"},
            "chart": reference.get("chart", {"bars": [], "frames": []}), "decisions": records,
            "fills": account.fills, "trades": account.closed_trades, "equity": equity.finish(),
            "diagnostics": {"attribution": attribution, "scenario": scenario, "auto_order": False,
                            "oos_status": "OOS_NOT_PROVEN", "funding_refusals": sum(r["reason"] == "MIN_LOT_BUDGET" for r in records)}}
