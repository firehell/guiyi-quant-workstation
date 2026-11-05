"""Public nwPathTrades/nwPathETA page illustration; never execution or a forecast fact.

The adapter owns physical/calculation boundaries. Prices stay decimal strings;
only dimensionless sample durations/ratios use the source's floating arithmetic.
"""

from datetime import date
from decimal import Decimal, InvalidOperation

VERSION = "guiyi_futures_historical_path_v1"


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
    open_reference=None,
    unified_trueup=False,
    trading_day=None,
):
    result = dict(
        version=VERSION,
        reference_policy="unified_trueup" if unified_trueup else "ordinary",
        status="unavailable",
        reason="TRADE_SAMPLES_MISSING",
        buys=[],
        sells=[],
        background=[],
        eta=None,
        holding=bool(open_reference) if unified_trueup else False,
        current=str(current) if _price(current) else None,
        target=str(target) if _price(target) else None,
        cost=str(cost) if _price(cost) else None,
        page_parity=False,
        executable=False,
    )
    if len(trades) + int(bool(open_reference) and unified_trueup) < 2 or not kline_dates:
        return result
    # Public strings are date-truncated even for minute K. No invented date grid.
    def day(value):
        return str(value)[:10]
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
    if open_reference and _price(open_reference.get("buyPrice")):
        buys.append(dict(date=day(open_reference["buyDate"]), price=str(open_reference["buyPrice"])))
    if len(buys) < 2 or not sells:
        return result
    result.update(
        status="ready",
        reason=None,
        buys=buys,
        sells=sells,
        holding=bool(open_reference) if unified_trueup else bool(trades[-1].get("forceClose")),
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
        if not a or not b:
            return None
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
            span(t.get("buyTradingDay", day(t["buyDate"])), t.get("sellTradingDay", day(t["sellDate"])))
            for t in trades
            if not t.get("forceClose") and t.get("sellDate")
        ]
        if holding
        else [
            span(a.get("sellTradingDay", day(a["sellDate"])), b.get("buyTradingDay", day(b["buyDate"])))
            for a, b in zip(trades, trades[1:])
            if a.get("sellDate") and b.get("buyDate")
        ]
    )
    if any(x is None or x < 0 for x in samples):
        eta["reason"] = "CALENDAR_PREFIX_MISSING"
        return result
    if len(samples) < 2:
        eta["reason"] = "SAMPLES_MISSING"
        return result
    entry = (
        (open_reference if unified_trueup else trades[-1])
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
    origin = entry.get("buyTradingDay" if holding else "sellTradingDay", day(entry["buyDate" if holding else "sellDate"]))
    if not origin:
        eta["reason"] = "TRADING_DAY_UNAVAILABLE"
        return result
    effective = max(trading_day or today, origin)
    elapsed = span(origin, effective) if weekly or (origin in calendar and effective in calendar) else None
    ratio = (
        min(1.0, max(0.0, abs(float(to) - float(now)) / abs(float(to) - float(source))))
        if float(to) != float(source)
        else 1.0
    )
    base = sum(samples) / len(samples)
    remain = base * ratio
    eta.update(
        status="ready",
        reason=None,
        base=base,
        remain=remain,
        elapsed=elapsed,
        ratio=ratio,
        samples=len(samples),
        overdue=elapsed > base if elapsed is not None else None,
        elapsed_reason=None if elapsed is not None else "CALENDAR_ELAPSED_UNAVAILABLE",
        date=None,
        date_status="unavailable",
        date_reason="CALENDAR_PROOF_UNAVAILABLE",
        date_source=None,
        date_limited=False,
        unit="周" if weekly else "个交易日",
        from_price=str(source),
        to_price=str(to),
    )
    return result
