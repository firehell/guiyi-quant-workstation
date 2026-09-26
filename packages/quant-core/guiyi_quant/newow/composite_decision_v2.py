"""CDV2 1.2.0 explanation only. Never a strategy or execution gate."""

from __future__ import annotations

VERSION = "newow_composite_decision_cdv2_1_2_0_v1"
SOURCE_SHA256 = "68c634c05bddc7191de884a37ae5c8877dfd8416a43e53d93c66838ea8585fbb"
PERIODS = ("week", "day", "m60")


def normalize_state(value, axis):
    text = str(value or "").lower()
    if text in ("buy", "hold", "yellow", "holding", "up"):
        return "up" if axis == "trend" else "holding"
    if text in ("sell", "wait", "blue", "cleared", "down"):
        return "down" if axis == "trend" else "cleared"
    return "unknown" if axis == "trend" else "idle"


def compute_cdv2(
    trend,
    oscillation,
    *,
    osc_age=-1,
    cross=None,
    volatility=None,
    j_reduce=False,
    care=False,
    tent=False,
):
    """Apply public priority chain to normalized, provenance-checked inputs.

    Cross age must be nonnegative. The adapter never invents batch age zero.
    Missing volatility has no penalty, but remains explicitly unknown.
    """
    ts = {p: normalize_state(trend.get(p), "trend") for p in PERIODS}
    os = {p: normalize_state(oscillation.get(p), "osc") for p in PERIODS}
    w, d, h = (ts[p] for p in PERIODS)
    ow, od, oh = (os[p] for p in PERIODS)
    tb = (
        "warning"
        if w == "down" and d == "up"
        else "bearish"
        if w == "down"
        else "cautious"
        if w == "up" and d == "down"
        else ("cautious" if h == "down" else "bullish")
        if w == d == "up"
        else "neutral"
    )
    ob = (
        "bullish"
        if ow == od == oh == "holding"
        else "bearish"
        if ow == od == oh == "cleared"
        else "bullish"
        if od == "holding" and oh != "cleared"
        else "bearish"
        if od == "cleared"
        else "bullish"
        if oh == "holding"
        else "bearish"
        if oh == "cleared"
        else "neutral"
    )
    if type(osc_age) is not int or osc_age < -1:
        raise ValueError("NEWOW_CDV2_INVALID_AGE")
    if cross is not None and (
        cross.get("type") not in ("buy", "sell")
        or type(cross.get("bars_ago")) is not int
        or cross["bars_ago"] < 0
    ):
        raise ValueError("NEWOW_CDV2_INVALID_CROSS")
    fresh = cross if cross and cross["bars_ago"] <= 2 else None
    mm = (
        "MM3"
        if fresh and fresh["type"] == "sell" and od == "holding"
        else "MM4"
        if fresh and fresh["type"] == "buy" and od == "cleared"
        else "MM1"
        if d == "up"
        and od == "cleared"
        and osc_age >= 3
        and not (fresh and fresh["type"] == "sell")
        else "MM2"
        if d == "down"
        and od == "holding"
        and osc_age >= 3
        and not (fresh and fresh["type"] == "buy")
        and tb != "bearish"
        else None
    )
    code = mm or f"{tb}-{ob}"

    def aligned(states, missing):
        values = [v for v in states.values() if v != missing]
        return len(values) >= 2 and len(set(values)) == 1

    same = tb == ob and tb in ("bullish", "bearish")
    r = (
        "R4"
        if same and aligned(ts, "unknown") and aligned(os, "idle")
        else "R3"
        if same
        else "R2"
        if mm or code in ("neutral-bullish", "neutral-bearish")
        else "R1"
        if tb in ("cautious", "warning")
        and ob != "neutral"
        or tb in ("bullish", "bearish")
        and ob in ("bullish", "bearish")
        and tb != ob
        else "R0"
    )
    explicit = [v for v in ts.values() if v != "unknown"]
    direction = (
        20
        if len(explicit) == 3 and len(set(explicit)) == 1
        else 12
        if len(explicit) == 3 and w == d
        else 6
        if len(explicit) == 3
        else (12 if len(set(explicit)) == 1 else 6)
        if len(explicit) == 2
        else (8 if w != "unknown" else 6)
        if explicit
        else 0
    )
    scores = {
        "trend": sum(n for p, n in zip(PERIODS, (12, 12, 6)) if ts[p] != "unknown"),
        "oscillation": sum(n for p, n in zip(PERIODS, (10, 12, 8)) if os[p] != "idle"),
        "resonance": {"R4": 20, "R3": 14, "R2": 10, "R1": 4, "R0": 0}[r],
        "direction": direction,
        "volatility": {"low": 0, "mid": -3, "high": -8}.get(volatility, 0),
    }
    deductions = {
        "j_reduce": -5 if j_reduce else 0,
        "care": -3 if care else 0,
        "tent": -3 if tent else 0,
    }
    extra = sum(deductions.values())
    total = max(0, min(100, sum(scores.values()) + extra))
    cert_cap = 100 if total >= 80 else 50 if total >= 60 else 30 if total >= 40 else 0
    res_cap = {"R4": 100, "R3": 60, "R2": 30, "R1": 10, "R0": 0}[r]
    exempt = bool(mm) or code in ("neutral-bullish", "neutral-bearish")
    cap = min(max(cert_cap, 30) if exempt else cert_cap, res_cap)
    gated = tb == "bearish" and not exempt
    insufficient = total < 40 and not exempt
    if gated or insufficient:
        cap = 0
    labels = {
        "bullish": ("建/加仓", "持仓观望", "建/加仓"),
        "bearish": ("减仓观望", "清/空仓", "清/空仓"),
        "cautious": ("谨慎持仓", "减仓观望", "谨慎持仓"),
        "warning": ("减仓观望",) * 3,
        "neutral": ("小仓试探", "逢高减仓", "等待"),
    }
    action = {
        "MM1": "逢高减仓·保留底仓",
        "MM2": "小仓试探·等趋势确认",
        "MM3": "逢高减仓·不追反弹",
        "MM4": "回补窗口·分批建仓",
    }.get(mm, labels[tb][("bullish", "bearish", "neutral").index(ob)])
    if insufficient:
        action = "等待信号"
    return {
        "formula_version": VERSION,
        "source_sha256": SOURCE_SHA256,
        "explanation_only": True,
        "executable": False,
        "trend_state": ts,
        "oscillation_state": os,
        "trend_bias": tb,
        "oscillation_bias": ob,
        "cross": cross,
        "oscillation_age": osc_age,
        "mismatch": mm,
        "mismatch_age": fresh["bars_ago"] if mm in ("MM3", "MM4") else osc_age,
        "resonance": r,
        "action_code": code,
        "action": action,
        "scores": scores,
        "deductions": deductions,
        "cert_extra": extra,
        "total": total,
        "volatility_level": volatility,
        "certainty_cap": cert_cap,
        "resonance_cap": res_cap,
        "reference_exposure_cap": cap,
        "reference_exposure_range": {
            100: "50%–100%",
            60: "30%–60%",
            50: "20%–50%",
            30: "10%–30%",
            10: "0%–10%",
            0: "",
        }[cap],
        "exempt": exempt,
        "bearish_gated": gated,
        "insufficient_overlay": insufficient,
        "is_probability": False,
        "is_margin_ratio": False,
    }
