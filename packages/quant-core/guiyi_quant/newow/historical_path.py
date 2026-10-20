"""Public nwPathTrades/nwPathETA page illustration; never execution or a forecast fact.

The adapter owns physical/calculation boundaries. Prices stay decimal strings;
only dimensionless sample durations/ratios use the source's floating arithmetic.
"""

from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from math import floor

VERSION = "newow_historical_path_v3402_v1"


def _price(value):
    try:
        v = Decimal(str(value))
        return v if v.is_finite() and v > 0 else None
    except (InvalidOperation, ValueError):
        return None


def build_historical_path(
    *,
    trades,
    kline_dates,
    daily_dates,
    period,
    today,
    current,
    target,
    cost,
    weekly_signals,
):
    result = dict(
        version=VERSION,
        status="unavailable",
        reason="TRADE_SAMPLES_MISSING",
        buys=[],
        sells=[],
        background=[],
        eta=None,
        holding=False,
        current=str(current) if _price(current) else None,
        target=str(target) if _price(target) else None,
        cost=str(cost) if _price(cost) else None,
        page_parity=True,
        executable=False,
    )
    if len(trades) < 2 or not kline_dates:
        return result
    # Public strings are date-truncated even for minute K. No invented date grid.
    day = lambda value: str(value)[:10]
    dates = [day(x) for x in kline_dates]
    start = dates[max(0, len(dates) - 1 - 20)]
    selected = [
        t
        for t in trades
        if day(t["buyDate"]) >= start
        or (
            not t.get("forceClose")
            and t.get("sellDate")
            and day(t["sellDate"]) >= start
        )
    ]
    if len(dates) <= 20:
        selected = trades
    if len(selected) < 2:
        selected = trades[-8:]
    buys = [
        dict(date=day(t["buyDate"]), price=str(t["buyPrice"]))
        for t in selected
        if _price(t.get("buyPrice"))
    ]
    sells = [
        dict(date=day(t["sellDate"]), price=str(t["sellPrice"]))
        for t in selected
        if not t.get("forceClose") and t.get("sellDate") and _price(t.get("sellPrice"))
    ]
    if len(buys) < 2 or not sells:
        return result
    result.update(
        status="ready",
        reason=None,
        buys=buys,
        sells=sells,
        holding=bool(trades[-1].get("forceClose")),
    )
    visible_dates = [d for d in dates if buys[0]["date"] <= d <= dates[-1]]
    if len(visible_dates) < 2:
        visible_dates = [buys[0]["date"], dates[-1]]
    n = len(visible_dates)
    result["axis_dates"] = [
        visible_dates[0],
        visible_dates[(n - 1) // 3],
        visible_dates[2 * (n - 1) // 3],
        visible_dates[-1],
    ]
    boundaries = sorted(
        (day(s["date"]), s["type"]) for s in weekly_signals if day(s["date"]) <= today
    )
    left, state = min(buys[0]["date"], sells[0]["date"]), "flat"
    for end, kind in boundaries:
        if end > left:
            result["background"].append(dict(start=left, end=end, state=state))
            left = end
        state = "hold" if kind == "buy" else "flat"
    if left <= today and boundaries:
        result["background"].append(dict(start=left, end=today, state=state))
    calendar = [day(x) for x in daily_dates]
    weekly = period == "1w"

    def index(d):
        return next(
            (i for i in range(len(calendar) - 1, -1, -1) if calendar[i] <= d), -1
        )

    def span(a, b):
        if weekly:
            return (date.fromisoformat(b) - date.fromisoformat(a)).days / 7
        ia, ib = index(a), index(b)
        return ib - ia if ia >= 0 and ib >= 0 else None

    eta = dict(status="unavailable", reason="CALENDAR_MISSING")
    result["eta"] = eta
    if not weekly and not calendar:
        return result
    holding = result["holding"]
    samples = (
        [
            span(day(t["buyDate"]), day(t["sellDate"]))
            for t in trades
            if not t.get("forceClose") and t.get("sellDate")
        ]
        if holding
        else [
            span(day(a["sellDate"]), day(b["buyDate"]))
            for a, b in zip(trades, trades[1:])
            if a.get("sellDate") and b.get("buyDate")
        ]
    )
    samples = [x for x in samples if x is not None]
    if len(samples) < 2:
        eta["reason"] = "SAMPLES_MISSING"
        return result
    entry = (
        trades[-1]
        if holding
        else next(
            (
                t
                for t in reversed(trades)
                if not t.get("forceClose") and t.get("sellDate")
            ),
            None,
        )
    )
    source = (
        _price(entry.get("buyPrice" if holding else "sellPrice")) if entry else None
    )
    to = _price(target if holding else cost)
    now = _price(current)
    if not entry or not source or not to or not now:
        eta["reason"] = "PRICE_OR_START_MISSING"
        return result
    origin = day(entry["buyDate" if holding else "sellDate"])
    effective = max(today, origin)
    elapsed = span(origin, effective)
    if elapsed is None:
        return result
    ratio = (
        min(1.0, max(0.0, abs(float(to) - float(now)) / abs(float(to) - float(source))))
        if float(to) != float(source)
        else 1.0
    )
    base = sum(samples) / len(samples)
    remain = base * ratio
    if weekly:
        expected = (
            date.fromisoformat(effective) + timedelta(days=floor(remain * 7 + 0.5))
        ).isoformat()
        limited = False
    else:
        at = index(effective)
        expected = calendar[min(len(calendar) - 1, max(0, at + floor(remain + 0.5)))]
        limited = at + floor(remain + 0.5) >= len(calendar) or effective > calendar[-1]
    result["axis_dates"][-1] = expected
    eta.update(
        status="ready",
        reason=None,
        base=base,
        remain=remain,
        elapsed=elapsed,
        ratio=ratio,
        samples=len(samples),
        overdue=elapsed > base,
        date=expected,
        date_limited=limited,
        unit="周" if weekly else "个交易日",
        from_price=str(source),
        to_price=str(to),
    )
    return result
