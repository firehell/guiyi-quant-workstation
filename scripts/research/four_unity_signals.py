"""Independent four-unity research signals, never a formal strategy kernel.

REFDATE(DJ, DATE) uses a daily date-lookup research convention. The original
software treatment of a varying DATE parameter has no external oracle.
FROMOPEN only feeds unused V5/V10/V20 and is deliberately omitted.
"""

from __future__ import annotations

import numpy as np
from guiyi_quant.indicators.htdy_original import compute_htdy_original, xma

CANDIDATES = ("trend_breakout", "bottom_latent", "pullback")


def ref(a, n=1):
    out = np.full(len(a), np.nan)
    if n < len(a):
        out[n:] = a[:-n]
    return out


def rolling(a, n, op):
    return np.array([op(a[max(0, i - n + 1) : i + 1]) for i in range(len(a))])


def smooth(a, alpha):
    out = np.full(len(a), np.nan)
    prev = np.nan
    for i, value in enumerate(a):
        if np.isfinite(value):
            prev = (
                value if not np.isfinite(prev) else alpha * value + (1 - alpha) * prev
            )
            out[i] = prev
    return out


def ema(a, n):
    return smooth(a, 2 / (n + 1))


def sma(a, n):
    return smooth(a, 1 / n)


def divide(a, b):
    return np.divide(a, b, out=np.full(len(a), np.nan), where=np.isfinite(b) & (b != 0))


def cross(a, b):
    b = np.full(len(a), b) if np.isscalar(b) else b
    return (a > b) & (ref(a) <= ref(b))


def filter_signal(flags, n):
    """TDX FILTER: suppress the following n bars after each accepted true."""
    out = np.zeros(len(flags), dtype=bool)
    next_allowed = 0
    for i, flag in enumerate(flags):
        if flag and i >= next_allowed:
            out[i] = True
            next_allowed = i + n + 1
    return out


def _capital_zero_funds(o, h, low, c, v):
    q0 = v / np.where(h == low, 4, h - low)
    jj = (h + low + c) / 3
    ddx = (
        q0 * (jj - np.minimum(c, o))
        + q0 * (np.minimum(c, o) - low)
        - q0 * (h - np.maximum(o, c))
        - q0 * (np.maximum(c, o) - jj)
    ) / 10000
    v2 = sma(np.where(c >= ref(c), ddx, -ddx / 100), 2)
    dy = np.zeros(len(c))
    dy[-1] = c[-1] < ref(c)[-1]
    return ddx, v2, ref(v2) - dy


def _dsq_escape_signals(a4, b1, c):
    bottom = (
        (a4 - b1 < 0.6)
        & (a4 < 40)
        & (c < rolling(c, 13, np.mean) * 0.996)
        & (c > ref(c))
    )
    top = (
        (a4 - b1 > 0.55)
        & (a4 > 70)
        & (c > rolling(c, 13, np.mean) * 0.96)
        & (c < ref(c))
    )
    return filter_signal(bottom, 10), filter_signal(top, 10)


def _chart(bars):
    n = len(bars)
    if not n:
        return []
    o, h, low, c, v = (
        np.array([float(b[k]) for b in bars])
        for k in ("open", "high", "low", "close", "volume")
    )
    ht = compute_htdy_original([b["date"] for b in bars], o, h, low, c, v)
    delta = c - ref(c)
    var23 = 100 * divide(xma(xma(delta, 6), 6), xma(xma(np.abs(delta), 6), 6))
    retrace = (
        (rolling(var23, 2, np.min) == rolling(var23, 7, np.min))
        & (rolling((var23 < 0).astype(float), 2, np.sum) > 0)
        & cross(var23, rolling(var23, 2, np.mean))
    )
    attention = (ht.zd1 > h) & retrace & (low <= ht.zd1)
    ddx, v2, dy2 = _capital_zero_funds(o, h, low, c, v)
    heavy = (
        (c > o)
        & (dy2 < 0.02)
        & (rolling(c, 5, np.mean) > rolling(c, 60, np.mean))
        & (divide(c, ref(c)) >= 1.02)
        & (h < ht.zk1)
        & (low < ht.zd1)
    )
    fly = ema(
        4
        * divide(
            c - rolling(low, 10, np.min),
            rolling(h, 25, np.max) - rolling(low, 10, np.min),
        ),
        4,
    )
    a2, a3 = rolling(low, 35, np.min), rolling(h, 35, np.max)
    a4 = ema(100 * divide((2 * c + h + low) / 4 - a2, a3 - a2), 9)
    b1 = ema(0.667 * ref(a4) + 0.333 * a4, 2)
    g2 = ema(sma(sma(100 * divide(c - a2, a3 - a2), 13), 13), 3)
    escape_bottom, escape_top = _dsq_escape_signals(a4, b1, c)
    ld = low - ref(low)
    var3 = 100 * divide(sma(np.abs(ld), 13), sma(np.maximum(ld, 0), 13))
    # IF(CLOSE*1.2, ...) is a truth test, not a missing comparison.
    var4 = ema(np.where(c * 1.2 != 0, var3 * 13, var3 / 13), 13)
    var8 = (
        ema(
            np.where(
                low <= rolling(low, 34, np.min),
                (var4 + 2 * rolling(var4, 34, np.max)) / 2,
                0,
            ),
            3,
        )
        / 618
        * (rolling(low, 56, np.min) != 0)
    )
    dj = ref(rolling(low, 100, np.min), 3)
    xga = (var8 > ref(var8)) & (low == dj)
    xg1 = xga.astype(float) > ref(xga.astype(float))
    explosion = filter_signal(xg1.astype(float) > ref(xg1.astype(float)), 5)
    fly_cross = cross(fly, 1.75)
    zd1_previous, g2_previous = ref(ht.zd1), ref(g2)
    rows = []
    for i in range(n):
        finite = all(
            np.isfinite(a[i]) for a in (fly, a4, b1, g2, var8, dj, ht.zd1, dy2)
        )
        ready = i >= 102 and finite
        conditions = dict(
            htdy_attention=bool(attention[i]),
            htdy_heavy_buy=bool(heavy[i]),
            htdy_buy_long=bool(ht.buy_observation[i]),
            htdy_sell_short=bool(ht.sell_observation[i]),
            zd1=float(ht.zd1[i]),
            zd1_up=bool(ht.zd1[i] > zd1_previous[i]),
            fly_value=float(fly[i]),
            fly_cross_175=bool(fly_cross[i]),
            dsq_g2_up=bool(g2[i] > g2_previous[i]),
            dsq_escape_bottom=bool(escape_bottom[i]),
            dsq_escape_top=bool(escape_top[i]),
            dtt_explosion_a=bool(explosion[i]),
        )
        entries = dict(
            trend_breakout=bool(
                ready
                and heavy[i]
                and conditions["fly_cross_175"]
                and conditions["dsq_g2_up"]
                and not escape_top[i]
                and not explosion[i]
            ),
            bottom_latent=bool(ready and explosion[i] and escape_bottom[i]),
            pullback=bool(
                ready
                and (attention[i] or ht.buy_observation[i])
                and conditions["zd1_up"]
                and 1.75 <= fly[i] <= 2
            ),
        )
        reasons = {
            k: ([] if ready else ["WARMUP_OR_NONFINITE_INPUT"]) for k in CANDIDATES
        }
        reasons["pullback"] = reasons["pullback"] + ["XMA6_EXTERNAL_ORACLE_UNRESOLVED"]
        rows.append(
            dict(
                date=bars[i]["date"],
                entries=entries,
                exit=bool(ht.sell_observation[i] or escape_top[i]),
                conditions=conditions,
                ready_inputs=ready,
                ready={k: ready and k != "pullback" for k in CANDIDATES},
                block_reasons=reasons,
            )
        )
    return rows


def compute_signals(bars):
    """Recompute each prefix and freeze only its last, contemporaneous value.

    Entries in blocked rows are convention-only research diagnostics. Consumers
    must enforce ready, independently of entries. Input is one physical contract.
    """
    dates = [b["date"] for b in bars]
    if dates != sorted(set(dates)):
        raise ValueError("daily dates must be unique and strictly increasing")
    for b in bars:
        values = [float(b[k]) for k in ("open", "high", "low", "close", "volume")]
        if (
            not all(np.isfinite(values))
            or min(values[:4]) <= 0
            or b["high"] < max(b["open"], b["close"], b["low"])
            or b["low"] > min(b["open"], b["close"])
            or b["volume"] < 0
        ):
            raise ValueError("invalid OHLCV")
    return dict(
        realtime=[_chart(bars[:i])[-1] for i in range(1, len(bars) + 1)],
        final_chart=_chart(bars),
        metadata=dict(
            strategy_code="four_unity_jm_daily_research_v1",
            capital=0,
            refdate_rule="daily date-lookup research convention: REFDATE(DJ,DATE)=DJ",
            refdate_oracle_status="externally_unresolved_varying_DATE_parameter",
            xma_rule="existing htdy_original clipped centered mean",
            xma6_oracle_status="externally_unresolved",
            warmup_bars=103,
            omitted_unused_chain="FROMOPEN -> V5 -> V10 -> V20",
            causal_policy="prefix recomputation, freeze endpoint only",
            research_only=True,
        ),
    )
