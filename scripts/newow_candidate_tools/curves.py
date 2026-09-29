"""Independent full CLOSED projection/DOM checks; no I/O or product algorithms."""

from datetime import datetime, timezone
from decimal import Decimal, localcontext
import math
from .context import need as require


def stamp(value):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    # JS Date.parse(YYYY-MM-DD) is UTC, independent of the host timezone.
    return (
        parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)
    ).timestamp()


def expected_curve(value, fusion=False):
    summary = (
        next(g for g in value["groups"] if g["model"] == "fusion")
        if fusion
        else value["summary"]
    )
    source = value["curve"] if fusion else value["curve_trades"]
    membership = "entry_in_window_v1" if fusion else summary["membership_policy"]
    trades = sorted(
        (
            t
            for t in source
            if t["status"] == "CLOSED" and t["statistics_membership"] == membership
        ),
        key=lambda t: (t["exit_bar_end"], t["reference_trade_id"]),
    )
    require(len(trades) == summary["closed_count"], "CLOSED_COUNT_MISMATCH")
    require(
        len({t["reference_trade_id"] for t in trades}) == len(trades),
        "CLOSED_ID_DUPLICATE",
    )
    if not trades:
        require(
            not source
            and (
                summary["sum_return_percentage_points"] is None
                or Decimal(summary["sum_return_percentage_points"]) == 0
            ),
            "ZERO_CLOSED_FACTS_CONFLICT",
        )
        return [], dict(
            closed_ids=[], cumulative_decimal=[], sum_decimal="0", closed_count=0
        )
    with localcontext() as ctx:
        ctx.prec = 200
        total = Decimal(0)
        sums = []
        for trade in trades:
            require(
                trade["exit_bar_end"] is not None
                and trade["reference_return_pct"] is not None,
                "CLOSED_FACT_MISSING",
            )
            number = Decimal(trade["reference_return_pct"])
            require(number.is_finite(), "RETURN_NOT_FINITE")
            total += number
            sums.append(total)
        declared = Decimal(summary["sum_return_percentage_points"])
        require(declared.is_finite(), "SUMMARY_NOT_FINITE")
        # Native summary uses precision 28 HALF_EVEN; mirror the UI's bounded
        # integer rounding allowance without allowing a fixed broad epsilon.
        scale = max(
            0,
            *[
                -x.as_tuple().exponent
                for x in [
                    declared,
                    *sums,
                    *[Decimal(t["reference_return_pct"]) for t in trades],
                ]
            ],
        )
        digits = max(
            1,
            *[
                len(format(abs(x), "f").split(".")[0])
                for x in [*sums, *[Decimal(t["reference_return_pct"]) for t in trades]]
            ],
        )
        allowance = (
            Decimal(10) ** (digits - 28) * len(trades)
            if scale + digits > 28
            else Decimal(0)
        )
        require(abs(total - declared) <= allowance, "CLOSED_SUM_MISMATCH")
    values = [float(x) for x in sums]
    require(all(math.isfinite(x) for x in values), "CUMULATIVE_NOT_FINITE")
    low = min(0, *values) * 1.1
    high = max(0, *values) * 1.1 or (0 if low < 0 else 1)
    y = lambda v: 140 - (v - low) / (high - low) * 140
    start = stamp(value["performance_since"])
    end = stamp(
        min(
            value["performance_through"],
            value.get("actual_available_through", value["performance_through"]),
        )
    )
    duration = end - start
    points = []
    for trade, number in zip(trades, values):
        if fusion:
            x = (
                (stamp(trade["exit_bar_end"]) + 28800 - start)
                / (duration + 86400)
                * 712
                if duration > 0
                else 712
            )
        else:
            x = (
                (stamp(trade["exit_trading_day"]) - start) / duration * 712
                if duration > 0
                else 712
            )
        points.append((x, y(number)))
    points = [(0, y(0)), *points, (712, points[-1][1])]
    return points, {
        "closed_ids": [t["reference_trade_id"] for t in trades],
        "cumulative_decimal": [str(x) for x in sums],
        "sum_decimal": str(total),
        "closed_count": len(trades),
    }


def curve_matches(actual, expected):
    try:
        points = [tuple(map(float, part.split(","))) for part in actual.split()]
        return len(points) == len(expected) and all(
            len(a) == 2
            and all(math.isfinite(n) for n in a)
            and abs(a[0] - b[0]) < 1e-7
            and abs(a[1] - b[1]) < 1e-7
            for a, b in zip(points, expected)
        )
    except (ValueError, TypeError, AttributeError):
        return False


def record_ids_match(items, dom):
    ids = [t["reference_trade_id"] for t in items]
    return (
        len(ids) == len(dom)
        and len(set(ids)) == len(ids)
        and all(
            isinstance(d, str) and isinstance(t, str) and bool(t) and d.endswith(t)
            for d, t in zip(dom, ids)
        )
    )


EMPTY_CURVE_STATUS = "暂无已完成参考交易；未清仓与中断结果不计入曲线。"


def validate_curve_ui(
    value: dict, curves: list[str], statuses: list[str], fusion: bool = False
) -> dict:
    expected, proof = expected_curve(value, fusion)
    if not expected:
        require(
            not curves and any(EMPTY_CURVE_STATUS in s for s in statuses),
            "EMPTY_CURVE_UI_UNPROVEN",
        )
    else:
        require(
            any(curve_matches(points, expected) for points in curves),
            "ALL_CURVE_POINTS_MISMATCH",
        )
    return dict(status="PASS", all_svg_points=len(expected), **proof)
