"""Explicit historical Paper replay; never a live subscription or broker adapter."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json

from app.market_data.actual_dominant_research import ActualDominantResearchSegmentLoader
from app.market_data.domain import BarFrequency
from app.market_data.newow.futures_validation import build_newow_research_bars
from app.market_data.newow.jm_pilot_research import load_jm_pilot_input
from guiyi_quant.newow.research_backtest import (
    DUAL_FUSION_CAUSAL_SIGNAL_VERSION, ResearchStrategy,
    build_strategy_intents_from_replay_segments,
)
from guiyi_quant.paper import (
    BeginTradingDay, FeeSchedule, Initialize, ObserveDecision, ObserveExecutionBar,
    PaperProfile, ResolveOrder, apply_command, apply_events,
)


def digest(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                             ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def number(value, *, positive=False):
    if not isinstance(value, str):
        raise ValueError("PAPER_EXECUTION_FACTS_MISSING")
    try:
        result = Decimal(value)
    except InvalidOperation:
        raise ValueError("PAPER_EXECUTION_FACTS_MISSING") from None
    if not result.is_finite() or (result <= 0 if positive else result < 0):
        raise ValueError("PAPER_EXECUTION_FACTS_MISSING")
    return result


@dataclass(frozen=True)
class HistoricalPlan:
    run_hash: str
    commands: tuple
    expected_summary: dict


def summary(state):
    return {
        "mode": "HISTORICAL_REPLAY", "cash": str(state.cash), "equity": str(state.equity),
        "trading_day": state.trading_day, "day_start_equity": str(state.day_start_equity),
        "daily_halt": state.daily_halt, "rollover_halt": state.rollover_halt,
        "position_qty": state.position_qty, "position_contract": state.position_contract,
        "order_count": len(state.orders), "fill_count": len(state.fills),
        "unresolved_orders": sum(o.status in ("PENDING", "CANCEL_REQUESTED", "UNKNOWN") for o in state.orders),
        "retrospective_execution_facts": True, "live_or_oos_evidence": False,
    }


def execution_command(bar, raw, run_hash, *, facts_hash=None):
    """Exact physical/date facts, no fee default or cross-day fallback."""
    try:
        if raw["schema_version"] != 1 or raw["source"] != "rqdata":
            raise ValueError("PAPER_EXECUTION_FACTS_MISSING")
        body = raw["contracts"][bar.physical_contract]
        day = bar.trading_day.isoformat()
        params = [r for r in body["parameters"] if r["date"] == day]
        limits = [r for r in body["daily"] if r["date"] == day]
        if len(params) != 1 or len(limits) != 1:
            raise ValueError("PAPER_EXECUTION_FACTS_MISSING")
        p, d = params[0], limits[0]
        money = p["commission_type"].lower()
        if money not in ("by_money", "by_volume"):
            raise ValueError("PAPER_EXECUTION_FACTS_MISSING")
        rates = [number(p[k]) for k in ("open_commission", "close_commission", "close_commission_today")]
        zero = Decimal(0)
        fact_id = f"rqdata:{facts_hash or digest(raw)}:{bar.physical_contract}:{day}"
        fees = FeeSchedule(*(x for fee in rates for x in
                             ((fee, zero) if money == "by_money" else (zero, fee))), source_id=fact_id)
        multiplier = number(body["instrument"]["contract_multiplier"], positive=True)
        tick = number(body["instrument"]["tick_size"], positive=True)
        margin = number(d["prev_settlement"], positive=True) * multiplier * number(p["long_margin_ratio"], positive=True)
        if bar.product != "jm" or bar.frequency != "1m" or not bar.observation_eligible or not bar.completed:
            raise ValueError("PAPER_REQUIRES_COMPLETED_PHYSICAL_1M")
        return ObserveExecutionBar(
            f"{run_hash}:bar:{bar.bar_end.isoformat()}", bar.bar_end, day, bar.physical_contract,
            bar.bar_end-timedelta(minutes=1), bar.bar_end, True,
            bar.open, bar.high, bar.low, bar.close, bar.volume, True,
            number(d["limit_up"], positive=True), number(d["limit_down"], positive=True),
            tick, 1, multiplier, fees, margin,
            bar.source_identity, fact_id, f"{fact_id}:limits", f"{fact_id}:prev-settlement-margin",
        )
    except (KeyError, TypeError, AttributeError, InvalidOperation):
        raise ValueError("PAPER_EXECUTION_FACTS_MISSING") from None


def build_historical_plan(source, minute_bars, raw, *, intents=None):
    """Preflight and replay completely before the first durable account write."""
    minute_bars = tuple(minute_bars)
    try:
        captured_at = datetime.fromisoformat(raw["captured_at"])
        if captured_at.tzinfo is None or len(raw["plan_hash"]) != 64:
            raise ValueError("PAPER_EXECUTION_FACTS_MISSING")
    except (KeyError, TypeError, ValueError):
        raise ValueError("PAPER_EXECUTION_FACTS_MISSING") from None
    if not minute_bars or any(a.bar_end >= b.bar_end for a, b in zip(minute_bars, minute_bars[1:])):
        raise ValueError("PAPER_1M_INPUT_INVALID")
    signal_by_end = {bar.bar_end: bar for bar in source.bars}
    minute_by_end = {bar.bar_end: bar for bar in minute_bars}
    if any(end not in minute_by_end or
           (bar.physical_contract, bar.trading_day, bar.close) !=
           (minute_by_end[end].physical_contract, minute_by_end[end].trading_day, minute_by_end[end].close)
           for end, bar in signal_by_end.items()):
        raise ValueError("PAPER_SIGNAL_EXECUTION_ALIGNMENT_FAILED")
    if intents is None:
        intents, _ = build_strategy_intents_from_replay_segments(source.replay_segments, ResearchStrategy.DUAL_FUSION)
    intents = tuple(i for i in intents if i.signal_bar_end in signal_by_end)
    if len({i.signal_bar_end for i in intents}) != len(intents):
        raise ValueError("PAPER_DUPLICATE_FUSED_TARGET")
    raw_hash = digest(raw)
    run_hash = digest({
        "version": "jm_paper_history_v1", "signal_input": source.input_sha256,
        "facts": raw_hash, "profile": "50000:1-long:2pct-day-start", "slippage_ticks": 1,
        "strategy": DUAL_FUSION_CAUSAL_SIGNAL_VERSION,
        "minutes": [[b.source_identity, b.physical_contract, b.trading_day.isoformat(), b.bar_end.isoformat(),
                     str(b.open), str(b.high), str(b.low), str(b.close), b.volume] for b in minute_bars],
        "intents": [[i.signal_bar_end.isoformat(), i.action.value, i.signal_formula_version] for i in intents],
    })
    profile = PaperProfile(f"jm-historical-{run_hash}", DUAL_FUSION_CAUSAL_SIGNAL_VERSION)
    by_end = {i.signal_bar_end: i for i in intents}
    commands = []
    state = None

    def append(command):
        nonlocal state
        state = apply_events(state, apply_command(state, command))
        commands.append(command)

    append(Initialize("initialize", minute_bars[0].bar_end-timedelta(minutes=1), profile))
    for bar in minute_bars:
        day = bar.trading_day.isoformat()
        if state.trading_day != day:
            append(BeginTradingDay(f"{run_hash}:day:{day}", bar.bar_end-timedelta(minutes=1), day,
                                   state.position_qty, state.position_contract,
                                   f"paper-replay:{state.last_event_id}"))
        append(execution_command(bar, raw, run_hash, facts_hash=raw_hash))
        if bar.bar_end in by_end:
            i = by_end[bar.bar_end]
            append(ObserveDecision(
                f"{run_hash}:decision:{bar.bar_end.isoformat()}", bar.bar_end,
                f"{run_hash}:{bar.bar_end.isoformat()}", source.input_sha256, i.action.value,
                bar.bar_end, bar.bar_end, day, bar.physical_contract, None,
                profile.profile_id, profile.strategy_version, "5m"))
        for order in state.orders:
            if order.status == "CANCEL_REQUESTED":
                append(ResolveOrder(f"{run_hash}:cancel:{order.order_id}", bar.bar_end,
                                    order.order_id, "CANCELLED", f"local-paper-cancel:{order.order_id}"))
    return HistoricalPlan(run_hash, tuple(commands), summary(state))


def load_historical_plan(market, raw, since: date, through: date):
    source = load_jm_pilot_input(market, since=since, actual_through=through)
    loader = ActualDominantResearchSegmentLoader(market)
    loaded = loader.load(
        symbol="jm", frequencies=(BarFrequency.M1,), since=since, through=through)
    minutes = build_newow_research_bars(loaded.results[BarFrequency.M1],
        authoritative_segments=loaded.authoritative_segments,
        expected_product="jm", expected_frequency=BarFrequency.M1)
    minutes = tuple(bar for bar in minutes if since <= bar.trading_day <= through)
    sessions = loader.sessions(symbol="jm", trading_days=tuple(sorted({b.trading_day for b in minutes})))
    if any(not any(window.start <= bar.bar_end-timedelta(minutes=1) and bar.bar_end <= window.end
                   for window in sessions[bar.trading_day]) for bar in minutes):
        raise ValueError("PAPER_EXECUTION_SESSION_UNPROVEN")
    return build_historical_plan(source, minutes, raw)


def commit_plan(ledger, account, plan):
    for start in range(0, len(plan.commands), 2000):
        ledger.execute_many(account, plan.commands[start:start+2000])
    state, sequence = ledger.load(account)
    actual = summary(state)
    if actual != plan.expected_summary:
        raise ValueError("PAPER_REPLAY_RECONCILIATION_FAILED")
    return {**actual, "run_hash": plan.run_hash, "sequence": sequence,
            "command_count": len(plan.commands), "verified": True}
