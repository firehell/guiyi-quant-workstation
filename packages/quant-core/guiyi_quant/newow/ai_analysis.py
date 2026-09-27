"""Public Niuwa summary ranking; page estimates, never ReferenceTrade or fills.

Source: stock_detail.html v3.3.59, runOscBacktest/runTrendBacktest/scoreCombos.
IEEE-754 intermediate arithmetic is intentional for the public-page oracle.
Persistable/delivered metric values are Decimal. The segment adapter is Guiyi's
own identity: each physical/quality segment is independently warmed and valued.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal, ROUND_HALF_UP, localcontext
from math import floor, isfinite, log1p
from typing import Sequence

PAGE_FORMULA = "newow_ai_summary_ranking_page_v1"
FUTURES_ADAPTER = "guiyi_newow_ai_segment_valuation_v1"
PAGE_SOURCE_SHA256 = "b12da74d89a7ac304d7479999d11f13ab53ced834a8472f937d78a0c1bd03709"


def fixed(value: float, digits: int) -> Decimal:
    if not isfinite(value):
        raise ValueError("NEWOW_DATA_IDENTITY_INVALID")
    with localcontext() as context:
        context.prec = 64
        return Decimal.from_float(value).quantize(Decimal(1).scaleb(-digits), rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class AnalysisSummary:
    cumulative_return: Decimal
    win_rate: int
    max_drawdown: Decimal
    trade_count: int
    terminal_valuation_count: int
    segment_count: int
    warming_segment_count: int


@dataclass(frozen=True)
class AnalysisCombo:
    strategy: str
    frequency: str
    since: str
    through: str | None
    source_bars: int
    input_sha256: str | None
    summary: AnalysisSummary | None
    reason_code: str | None = None
    score: Decimal | None = None
    confidence: str | None = None
    is_best: bool = False


def estimate_segments(segments: Sequence[Sequence[tuple[Decimal, Decimal, Decimal]]], strategy: str) -> AnalysisSummary | None:
    """Each input triple is high/low/close; callers own time and segment validation.

    A boundary terminal estimate is counted ONLY in this page analysis. There is
    no cross-contract price pairing, and no strategy CLEAR or account fill.
    Drawdown is peak minus marked cumulative percentage points, not capital %.
    """
    if strategy not in ("trend", "oscillation"):
        raise ValueError("NEWOW_INVALID_QUERY")
    cumulative = peak = drawdown = 0.0
    wins = count = terminal = used = warming = 0
    for segment in segments:
        if len(segment) < 11:
            warming += 1
            continue
        used += 1
        rows = []
        for row in segment:
            if any(not isinstance(x, Decimal) or not x.is_finite() or x <= 0 for x in row):
                raise ValueError("NEWOW_DATA_IDENTITY_INVALID")
            high, low, close = map(float, row)
            if not all(isfinite(x) and x > 0 for x in (high, low, close)) or not low <= close <= high:
                raise ValueError("NEWOW_DATA_IDENTITY_INVALID")
            rows.append((high, low, close))
        jj = [(close + high + low) / 3 for high, low, close in rows]
        # Public calcMAFrom uses partial means and sums newest -> oldest.
        band = [sum(reversed(jj[max(0, i-9):i+1])) / min(i+1, 10) for i in range(len(rows))]
        states = [close >= b for (_, _, close), b in zip(rows, band)]
        buy: float | None = None
        for i in range(9, len(rows)):
            high, low, close = rows[i]
            if strategy == "oscillation":
                if buy is not None and high >= max(row[0] for row in rows[i-9:i+1]):
                    pct = (high - buy) / buy * 100
                    cumulative += pct
                    count += 1
                    wins += int(pct > 0)
                    buy = None
                # CLEAR -> BUILD on the same bar is deliberately two independent ifs.
                if buy is None and low <= min(row[1] for row in rows[i-9:i+1]):
                    buy = low
            else:
                if states[i] is True and states[i-1] is False and buy is None:
                    buy = band[i]
                elif states[i] is False and states[i-1] is True and buy is not None:
                    pct = (band[i] - buy) / buy * 100
                    cumulative += pct
                    count += 1
                    wins += int(pct > 0)
                    buy = None
            equity = cumulative + ((close - buy) / buy * 100 if buy is not None else 0)
            peak = max(peak, equity)
            drawdown = max(drawdown, peak - equity)
        if buy is not None:
            pct = (rows[-1][2] - buy) / buy * 100
            cumulative += pct
            count += 1
            wins += int(pct > 0)
            terminal += 1
    if not used:
        return None
    return AnalysisSummary(fixed(cumulative, 2), floor(wins / count * 100 + .5) if count else 0,
                           fixed(drawdown, 2), count, terminal, used, warming)


def rank_combos(combos: Sequence[AnalysisCombo]) -> tuple[AnalysisCombo, ...]:
    """Return stable display order, with the public sample/tie-break rules."""
    values = [replace(c, score=None, confidence=None, is_best=False) for c in combos]
    valid = [i for i, c in enumerate(values) if c.summary is not None and c.summary.trade_count >= 3]
    if not valid:
        return tuple(values)
    summaries = [values[i].summary for i in valid]
    cum = [float(s.cumulative_return) for s in summaries]
    cal = [log1p(max(0, float(s.cumulative_return) / float(s.max_drawdown) if s.max_drawdown > 0 else
                     999 if s.cumulative_return > 0 else 0)) for s in summaries]
    acc = [s.win_rate for s in summaries]
    def normalize(numbers):
        lo, hi = min(numbers), max(numbers)
        return [(v - lo) / ((hi - lo) or 1) for v in numbers]
    for i, a, b, c in zip(valid, normalize(cum), normalize(cal), normalize(acc)):
        ample = values[i].summary.trade_count >= 10
        values[i] = replace(values[i], score=fixed((.40*a + .35*b + .25*c) * (1 if ample else .85), 4),
                            confidence="high" if ample else "mid")
    best = max(valid, key=lambda i: (values[i].score, values[i].summary.trade_count))
    values[best] = replace(values[best], is_best=True)
    return tuple(values)
