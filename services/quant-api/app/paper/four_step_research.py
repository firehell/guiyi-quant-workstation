"""In-memory, fixed-lot D1 comparison on the shared Paper execution facts."""
from dataclasses import dataclass
from decimal import Decimal

from guiyi_quant.newow.causal_matrix_signals import CausalMatrixStrategy, build_causal_matrix_intents
from guiyi_quant.newow.research_backtest import BacktestAction, ResearchStrategy, build_strategy_intents_from_replay_segments
from guiyi_quant.paper import execution_fill_price

VERSION = "newow_four_step_causal_fixed_lots_v1"
ARMS = ("four_step", "dual_fusion", "oscillation")
CAPITAL = Decimal(50_000)


@dataclass(frozen=True)
class Target:
    lots: int
    close_first: bool = False


def four_step_targets(bars, oscillation, trend):
    by_end = {}
    for source, intents in enumerate((oscillation, trend)):
        for intent in intents:
            by_end.setdefault(intent.signal_bar_end, []).append((intent.action == BacktestAction.BUILD, source))
    held = 0
    owner = None
    output = {}
    for bar in bars:
        new_owner = bar.physical_contract, bar.segment_id
        if new_owner != owner:
            owner, held = new_owner, 0
        before = held
        clear = False
        for buying, source in sorted(by_end.get(bar.bar_end, ())):
            if not buying:
                clear = clear or held > 0
                held = 0
            elif source == 0 and not held:
                held = 1
            elif source == 1 and held == 1:
                held = 2
        if before != held or clear:
            output[bar.bar_end] = Target(held, clear)
    return output


@dataclass(frozen=True)
class Lot:
    price: Decimal
    trading_day: str
    multiplier: Decimal


def replay_targets(minutes, targets, *, owners=None):
    """Preserve unresolved exposure as marks at owner boundaries."""
    lots: list[Lot] = []
    desired = 0
    must_close = False
    effective_after = None
    net = fees = frozen_mark = drawdown = Decimal(0)
    peak = CAPITAL
    prev = None
    owner = None
    interrupted = []
    entries = exits = cycles = rejected = 0
    last_mark = Decimal(0)
    touched = 0

    def mark(close):
        return sum(((close - lot.price) * lot.multiplier for lot in lots), Decimal(0))

    for bar in minutes:
        current_owner = owners[bar.bar_end] if owners is not None else bar.physical_contract
        if prev is not None and current_owner != owner:
            if lots:
                interrupted.append({"physical_contract": prev.physical_contract, "at": prev.bar_end.isoformat(),
                                    "open_lots": len(lots), "unrealized_pnl": str(mark(prev.close))})
                frozen_mark += mark(prev.close)
            lots.clear()
            desired = 0
            must_close = False
            effective_after = None
        prev, owner = bar, current_owner
        # A bar that starts exactly at the decision time has already opened
        # when the decision becomes known. Keep the shared Paper strict boundary.
        can_execute = effective_after is not None and bar.bar_start > effective_after
        available = bar.volume
        if must_close and not lots:
            must_close = False
        if can_execute and (must_close or desired < len(lots)) and lots:
            close = execution_fill_price("CLOSE", bar)
            if close is None:
                rejected += 1
            else:
                count = min(available, len(lots) if must_close else len(lots) - desired)
                available -= count
                for _ in range(count):
                    lot = lots.pop(0)
                    if bar.multiplier != lot.multiplier:
                        raise ValueError("FOUR_STEP_EXECUTION_MULTIPLIER_DRIFT")
                    offset = "close_today" if lot.trading_day == bar.trading_day else "close"
                    fee = bar.fees.amount(offset, close, lot.multiplier)
                    net += (close - lot.price) * lot.multiplier - fee
                    fees += fee
                    exits += 1
                cycles += int(not lots)
                must_close = must_close and bool(lots)
        if can_execute and not must_close and len(lots) < desired and (available > 0 or bar.volume == 0):
            price = execution_fill_price("OPEN", bar)
            if price is None:
                rejected += 1
            else:
                for _ in range(min(available, desired - len(lots))):
                    fee = bar.fees.amount("open", price, bar.multiplier)
                    lots.append(Lot(price, bar.trading_day, bar.multiplier))
                    net -= fee
                    fees += fee
                    entries += 1
        if lots and any(lot.multiplier != bar.multiplier for lot in lots):
            raise ValueError("FOUR_STEP_EXECUTION_MULTIPLIER_DRIFT")
        last_mark = mark(bar.close)
        equity = CAPITAL + net + frozen_mark + last_mark
        peak = max(peak, equity)
        drawdown = max(drawdown, (peak - equity) * 100 / peak)
        if bar.bar_end in targets:
            target = targets[bar.bar_end]
            desired = target.lots
            effective_after = bar.bar_end
            must_close = must_close or (target.close_first and bool(lots))
            touched += 1
    if touched != len(targets):
        raise ValueError("FOUR_STEP_SIGNAL_EXECUTION_ALIGNMENT_FAILED")
    m2m = net + frozen_mark + last_mark
    return {
        "net_pnl_marked": str(m2m), "net_cash_pnl": str(net), "return_pct": str(m2m * 100 / CAPITAL),
        "max_drawdown_pct": str(drawdown), "round_trips": cycles, "entry_lots": entries, "exit_lots": exits,
        "fees": str(fees), "blocked_fill_minutes": rejected, "rollover_interruptions": interrupted,
        "end_open_lots": len(lots), "end_pending_target": desired if must_close or desired != len(lots) else None,
        "signal_count": touched,
    }


def compare_four_step(source, minutes, fact_hash, clock_hash, *, owners, sample="development"):
    by_end = {bar.bar_end: bar for bar in minutes}
    if source.frequency.value != "1d" or any(
        bar.bar_end not in by_end or
        (bar.physical_contract, bar.trading_day.isoformat()) !=
        (by_end[bar.bar_end].physical_contract, by_end[bar.bar_end].trading_day)
        for bar in source.bars
    ):
        raise ValueError("FOUR_STEP_SIGNAL_EXECUTION_ALIGNMENT_FAILED")
    osc, osc_versions = build_strategy_intents_from_replay_segments(source.replay_segments, ResearchStrategy.OSCILLATION)
    trend, trend_versions = build_strategy_intents_from_replay_segments(source.replay_segments, ResearchStrategy.TREND)
    results = {"four_step": replay_targets(minutes, four_step_targets(source.bars, osc, trend), owners=owners)}
    versions = {"four_step": (VERSION, *osc_versions, *trend_versions)}
    for arm in ARMS[1:]:
        intents, versions[arm] = build_causal_matrix_intents(source.replay_segments, CausalMatrixStrategy(arm))
        targets = {item.signal_bar_end: Target(2 if item.action == BacktestAction.BUILD else 0) for item in intents}
        results[arm] = replay_targets(minutes, targets, owners=owners)
    return {"model": VERSION, "since": str(source.requested_since), "through": str(source.actual_through),
            "signal_input_sha256": source.input_sha256, "execution_input_sha256": clock_hash, "facts_sha256": fact_hash,
            "position_cap_lots": 2, "account_return_denominator": str(CAPITAL), "portfolio_allocation": False,
            "sample": sample, "independent_oos": False, "formula_versions": versions, "results": results}
