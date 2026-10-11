"""Fixed-rule JM comparisons using the existing Paper event reducer."""
from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

from app.paper.history import digest, execution_command, summary
from guiyi_quant.newow.causal_matrix_signals import (
    CausalMatrixStrategy, build_causal_matrix_intents,
)
from guiyi_quant.paper import (
    BeginTradingDay, Initialize, ObserveDecision, PaperProfile, ResolveOrder,
    apply_command, apply_events,
)

MATRIX_VERSION = "jm_paper_fixed_risk_matrix_v1"
SCENARIOS = ("baseline", "double_commission", "double_slippage")


def prepare_execution(minutes, facts):
    """Reuse exact daily fee/limit/margin adapter; immutable commands are templates."""
    fact_hash = digest(facts)
    templates = tuple(execution_command(b, facts, "matrix-template", facts_hash=fact_hash) for b in minutes)
    if not templates or any(a.bar_end >= b.bar_end for a, b in zip(templates, templates[1:])):
        raise ValueError("MATRIX_EXECUTION_CLOCK_INVALID")
    clock_hash = digest([[b.market_fact_id, b.physical_contract, b.trading_day,
                          b.bar_start.isoformat(), b.bar_end.isoformat(),
                          str(b.open), str(b.high), str(b.low), str(b.close), b.volume]
                         for b in templates])
    return templates, fact_hash, clock_hash


def run_matrix_cell(source, templates, fact_hash, clock_hash, strategy, *,
                    scenario="baseline", physical_contract=None):
    if scenario not in SCENARIOS:
        raise ValueError("MATRIX_SCENARIO_INVALID")
    strategy = CausalMatrixStrategy(strategy)
    intents, versions = build_causal_matrix_intents(source.replay_segments, strategy)
    signal_bars = {b.bar_end: b for b in source.bars
                   if physical_contract is None or b.physical_contract == physical_contract}
    selected = tuple(b for b in templates if physical_contract is None or b.physical_contract == physical_contract)
    if not selected or not signal_bars:
        raise ValueError("MATRIX_WINDOW_EMPTY")
    by_end = {b.bar_end: b for b in selected}
    # D1/W1 are independently sourced prices: require their completed endpoint,
    # physical owner and trading day, never claim cross-frequency close parity.
    if any(end not in by_end or (bar.physical_contract, bar.trading_day.isoformat()) !=
           (by_end[end].physical_contract, by_end[end].trading_day)
           for end, bar in signal_bars.items()):
        raise ValueError("MATRIX_SIGNAL_EXECUTION_ALIGNMENT_FAILED")
    intents_by_end = {i.signal_bar_end: i for i in intents if i.signal_bar_end in signal_bars}
    if len(intents_by_end) != len([i for i in intents if i.signal_bar_end in signal_bars]):
        raise ValueError("MATRIX_DUPLICATE_TARGET")
    run_hash = digest({"version": MATRIX_VERSION, "frequency": source.frequency,
        "strategy": strategy.value, "versions": versions, "signal_input": source.input_sha256,
        "execution_input": clock_hash, "facts": fact_hash, "scenario": scenario,
        "physical_diagnostic": physical_contract, "initial_cash": "50000", "lots": 1, "day_stop": "0.02"})
    frequency = str(source.frequency)
    profile = PaperProfile(f"matrix-{run_hash}", versions[0], frequency=frequency)
    state = None
    count = 0
    peak = Decimal("50000")
    max_dd = Decimal(0)
    halt_days = set()
    daily = {}
    interrupted = None
    started_at = selected[0].bar_start

    def append(command):
        nonlocal state, count, peak, max_dd
        events = apply_command(state, command)
        state = apply_events(state, events)
        count += len(events)
        peak = max(peak, state.equity)
        max_dd = max(max_dd, (peak - state.equity) / peak * 100)
        if state.daily_halt:
            halt_days.add(state.trading_day)

    append(Initialize("initialize", started_at, profile))
    for original in selected:
        if state.trading_day != original.trading_day:
            append(BeginTradingDay(f"{run_hash}:day:{original.trading_day}", original.bar_start,
                original.trading_day, state.position_qty, state.position_contract,
                f"paper-reducer:{state.last_event_id}"))
        fees = original.fees
        if scenario == "double_commission":
            fees = replace(fees, **{key: getattr(fees, key) * 2 for key in (
                "open_rate", "open_per_contract", "close_rate", "close_per_contract",
                "close_today_rate", "close_today_per_contract")},
                source_id=f"{fees.source_id}:double-commission-assumption")
        bar = replace(original, command_id=f"{run_hash}:bar:{original.bar_end.isoformat()}",
                      fees=fees, slippage_ticks=2 if scenario == "double_slippage" else 1)
        append(bar)
        if state.rollover_halt:
            interrupted = {"at": bar.bar_end.isoformat(), "new_contract": bar.physical_contract,
                           "old_position": state.position_contract, "reason": "PAPER_ROLLOVER_INTERRUPTED"}
            break
        intent = intents_by_end.get(bar.bar_end)
        if intent is not None:
            append(ObserveDecision(f"{run_hash}:decision:{bar.bar_end.isoformat()}", bar.bar_end,
                f"{run_hash}:{bar.bar_end.isoformat()}", source.input_sha256, intent.action.value,
                bar.bar_end, bar.bar_end, bar.trading_day, bar.physical_contract, None,
                profile.profile_id, profile.strategy_version, frequency))
        for order in state.orders:
            if order.status == "CANCEL_REQUESTED":
                append(ResolveOrder(f"{run_hash}:cancel:{order.order_id}", bar.bar_end,
                                    order.order_id, "CANCELLED", f"local-paper-cancel:{order.order_id}"))
        daily[bar.trading_day] = {"equity": str(state.equity), "day_start_equity": str(state.day_start_equity),
                                  "halted": state.daily_halt, "position_qty": state.position_qty}
    assert state is not None
    closed = [f for f in state.fills if f.side == "CLOSE"]
    return {**summary(state), "strategy": strategy.value, "frequency": source.frequency,
        "scenario": scenario, "run_hash": run_hash, "formula_versions": versions,
        "signal_input_hash": source.input_sha256, "execution_input_hash": clock_hash, "facts_hash": fact_hash,
        "status": "PAPER_ROLLOVER_INTERRUPTED" if interrupted else "COMPLETE",
        "annual_eligible": physical_contract is None and interrupted is None and bool(closed),
        "scope": "continuous_year" if physical_contract is None else "independent_physical_segment",
        "physical_contract": physical_contract, "interruption": interrupted,
        "started_at": started_at.isoformat(), "processed_through": state.last_bar_end.isoformat(),
        "valuation_at": state.mark_at.isoformat() if state.mark_at else None,
        "planned_through": selected[-1].bar_end.isoformat(), "event_count": count,
        "last_event_id": state.last_event_id, "closed_trades": len(closed),
        "fees_paid": str(sum((f.fee for f in state.fills), Decimal(0))),
        "net_pnl": str(state.equity - Decimal("50000")),
        "account_return_pct": str((state.equity / Decimal("50000") - 1) * 100),
        "mark_to_market_max_drawdown_pct": str(max_dd), "halt_days": sorted(halt_days),
        "daily": daily, "selection_overlap": True, "independent_oos": False, "promotion": False,
        "persistence": "in_memory_same_paper_reducer_not_a_new_postgresql_account"}
