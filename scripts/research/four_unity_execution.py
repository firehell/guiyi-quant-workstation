"""One-lot offline LONG experiment. No account, orders, persistence or broker I/O.

Reuse the existing Paper price eligibility helper without creating Paper state.
Intraminute stop touches are only known at minute end; they queue a market exit
at the next strictly later minute start. Opening gaps through stops exit at open.
"""

from __future__ import annotations

from collections import Counter
from datetime import timedelta
from decimal import Decimal, localcontext
from hashlib import sha256
from math import sqrt
from types import SimpleNamespace

from guiyi_quant.paper import _fill_price

D = Decimal
ZERO = D("0")
VERSION = "four_unity_long_next_minute_v1"


def price_at(execution, side, ticks):
    b, f = execution.bar, execution.facts
    return _fill_price(
        SimpleNamespace(side=side, limit_price=None),
        SimpleNamespace(
            volume=b.volume,
            session_open=True,
            open=b.open,
            limit_down=f.limit_down,
            limit_up=f.limit_up,
            tick_size=f.tick_size,
            slippage_ticks=ticks,
        ),
    )


def run_segment(signals, minutes, candidate, ticks, *, terminal="OPEN"):
    """One contiguous fully verified physical-owner execution interval."""
    if ticks not in (0, 1, 2):
        raise ValueError("SLIPPAGE_INVALID")
    if terminal not in ("OPEN", "ROLLOVER_INTERRUPTED", "DATA_INTERRUPTED"):
        raise ValueError("TERMINAL_INVALID")
    if any(a["at"] >= b["at"] for a, b in zip(signals, signals[1:])):
        raise ValueError("SIGNALS_NOT_ORDERED")
    if any(a.bar.bar_end >= b.bar.bar_end for a, b in zip(minutes, minutes[1:])):
        raise ValueError("MINUTES_NOT_ORDERED")
    if len({m.bar.physical_contract for m in minutes}) > 1:
        raise ValueError("PHYSICAL_CONTRACT_MISMATCH")
    position = pending = None
    exit_pending = None
    trades, equity, decisions = [], [], []
    rejected = Counter()
    realized, index, unfilled = ZERO, 0, 0
    last_exit_signal_at = None
    for ex in minutes:
        b, f = ex.bar, ex.facts
        start = b.bar_end - timedelta(minutes=1)
        while index < len(signals) and signals[index]["at"] < start:
            s = signals[index]
            index += 1
            if s["exit"]:
                last_exit_signal_at = s["at"]
                if pending is not None:
                    unfilled += 1
                    pending = None
                if position is not None and exit_pending is None:
                    exit_pending = {"at": s["at"], "reason": "SIGNAL_EXIT"}
                continue
            if (
                position is None
                and exit_pending is None
                and s["entries"].get(candidate)
                and s["ready"].get(candidate)
                and not s.get("block_reasons", {}).get(candidate)
                and (last_exit_signal_at is None or s["at"] > last_exit_signal_at)
            ):
                if pending is not None:
                    unfilled += 1
                pending = s
                decisions.append(
                    {
                        "at": s["at"].isoformat(),
                        "action": "ENTRY_SIGNAL",
                        "candidate": candidate,
                        "conditions": s.get("conditions", {}),
                    }
                )
        exited = False
        if position is not None:
            # Opening-price stop has priority over a queued signal exit.
            gap_stop = b.open <= position["stop"]
            if gap_stop:
                exit_pending = {
                    "at": start - timedelta(microseconds=1),
                    "reason": "STOP",
                }
            if exit_pending and exit_pending["at"] < start:
                p = price_at(ex, "CLOSE", ticks)
                if p is None:
                    rejected["EXIT_NOT_EXECUTABLE"] += 1
                else:
                    kind = (
                        "close_today"
                        if b.trading_day == position["entry_day"]
                        else "close"
                    )
                    close_fee = f.fees.amount(kind, p, f.multiplier)
                    gross = (p - position["entry_price"]) * f.multiplier
                    fees = close_fee + position["entry_fee"]
                    net = gross - fees
                    realized += net
                    trades.append(
                        {
                            **position,
                            "entry_day": str(position["entry_day"]),
                            "exit_at": start.isoformat(),
                            "exit_observed_at": b.bar_end.isoformat(),
                            "exit_price": p,
                            "exit_reason": exit_pending["reason"],
                            "status": "CLOSED",
                            "exit_fee_kind": kind,
                            "exit_fact_id": f.source_id,
                            "gross_pnl": gross,
                            "fees": fees,
                            "net_pnl": net,
                        }
                    )
                    position = exit_pending = None
                    exited = True
        if pending is not None and position is None and not exited:
            p = price_at(ex, "OPEN", ticks)
            stop = pending["low"] - f.tick_size
            if p is None:
                rejected["ENTRY_NOT_EXECUTABLE"] += 1
            elif p <= stop:
                rejected["ENTRY_ALREADY_BELOW_STOP"] += 1
                unfilled += 1
                pending = None
            else:
                identity = f"{VERSION}|{candidate}|{ticks}|{b.physical_contract}|{pending['at'].isoformat()}"
                position = {
                    "trade_id": sha256(identity.encode()).hexdigest()[:24],
                    "physical_contract": b.physical_contract,
                    "signal_at": pending["at"].isoformat(),
                    "entry_at": start.isoformat(),
                    "entry_observed_at": b.bar_end.isoformat(),
                    "entry_day": b.trading_day,
                    "entry_price": p,
                    "entry_fee": f.fees.amount("open", p, f.multiplier),
                    "stop": stop,
                    "entry_fact_id": f.source_id,
                }
                pending = None
        if position is not None and b.low <= position["stop"] and exit_pending is None:
            exit_pending = {"at": b.bar_end, "reason": "STOP"}
        mark = realized
        if position is not None:
            mark += (b.close - position["entry_price"]) * f.multiplier - position[
                "entry_fee"
            ]
        equity.append({"at": b.bar_end.isoformat(), "pnl": mark})
    if pending:
        unfilled += 1
    unobserved = [
        {"at": s["at"].isoformat(), "entries": s["entries"], "exit": s["exit"]}
        for s in signals[index:]
        if s["entries"].get(candidate) or s["exit"]
    ]
    unclosed = []
    if position:
        unclosed.append(
            {
                **position,
                "entry_day": str(position["entry_day"]),
                "status": terminal,
                "pending_exit": exit_pending["reason"] if exit_pending else None,
            }
        )
    return {
        "trades": trades,
        "unclosed": unclosed,
        "equity": equity,
        "decisions": decisions,
        "unfilled_entries": unfilled,
        "rejections": dict(rejected),
        "signals_without_later_minute": unobserved,
    }


def _ratio(a, b):
    return a / b if b else None


def summarize(trades, unclosed):
    with localcontext() as ctx:
        ctx.prec = 28
        n = len(trades)
        wins = sum(t["net_pnl"] > 0 for t in trades)
        positive = sum((t["net_pnl"] for t in trades if t["net_pnl"] > 0), ZERO)
        losses = -sum((t["net_pnl"] for t in trades if t["net_pnl"] < 0), ZERO)
        losing_n = sum(t["net_pnl"] < 0 for t in trades)
        gp = sum((t["gross_pnl"] for t in trades if t["gross_pnl"] > 0), ZERO)
        gl = -sum((t["gross_pnl"] for t in trades if t["gross_pnl"] < 0), ZERO)
        ci = None
        if n:
            p, z = wins / n, 1.959963984540054
            centre = (p + z * z / (2 * n)) / (1 + z * z / n)
            half = z * sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
            ci = [100 * max(0, centre - half), 100 * min(1, centre + half)]
        peak = cumulative = drawdown = ZERO
        for t in sorted(trades, key=lambda x: x["exit_at"]):
            cumulative += t["net_pnl"]
            peak = max(peak, cumulative)
            drawdown = max(drawdown, peak - cumulative)
        return {
            "closed_trades": n,
            "wins": wins,
            "losses": losing_n,
            "breakeven": n - wins - losing_n,
            "win_rate_pct": wins / n * 100 if n else None,
            "wilson_95_pct": ci,
            "net_pnl_per_lot": cumulative,
            "gross_pnl_per_lot": sum((t["gross_pnl"] for t in trades), ZERO),
            "fees_per_lot": sum((t["fees"] for t in trades), ZERO),
            "net_profit_factor": _ratio(positive, losses),
            "gross_profit_factor": _ratio(gp, gl),
            "net_average_win_loss_ratio": _ratio(
                _ratio(positive, D(wins)) or ZERO, _ratio(losses, D(losing_n)) or ZERO
            ),
            "closed_trade_max_drawdown_per_lot": drawdown,
            "unclosed_statuses": dict(Counter(t["status"] for t in unclosed)),
            "sample_warning": "SMALL_SAMPLE"
            if n < 30
            else "HISTORICAL_EXPLORATION_ONLY",
        }
