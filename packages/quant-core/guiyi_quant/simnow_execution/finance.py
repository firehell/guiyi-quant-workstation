"""Actual native commission counters and equity, isolated from reference returns."""

from dataclasses import dataclass
from decimal import Decimal
from .inventory import number, trade_identity, native_hash, linked_trade
from .model import Fee


@dataclass(frozen=True)
class Performance:
    account_id: str
    source_id: str
    equity: Decimal
    available: Decimal
    commission: Decimal
    closed_profit: Decimal
    position_profit: Decimal
    net_cashflow: Decimal | None
    net_profit: Decimal | None
    return_ratio: Decimal | None
    status: str


def actual_fee(before, after, state, journal):
    if before.account_id != after.account_id or state.account_id != after.account_id:
        raise ValueError("FEE_ACCOUNT_MISMATCH")
    if before.trading_day != after.trading_day or before.at > after.started_at:
        return (), "FEE_COUNTER_CONTINUITY_UNPROVEN"
    left, right = before.data, after.data
    f0, f1 = left["funds"][0], right["funds"][0]
    if any(number(f0[k]) != number(f1[k]) for k in ("Deposit", "Withdraw")):
        return (), "FEE_WINDOW_HAS_CASHFLOW"
    old = {trade_identity(r): r for r in left["trades"]}
    new = {trade_identity(r): r for r in right["trades"]}
    if not set(old) <= set(new) or any(new[k] != v for k, v in old.items()):
        return (), "FEE_TRADE_HISTORY_CHANGED"
    delta = number(f1["Commission"]) - number(f0["Commission"])
    added = set(new) - set(old)
    if not added:
        return (), "NO_NEW_TRADE" if delta == 0 else "FEE_COUNTER_CHANGED_WITHOUT_TRADE"
    if len(added) != 1 or delta < 0:
        return (), "FEE_NOT_UNIQUELY_ATTRIBUTABLE"
    identity = next(iter(added))
    row = linked_trade(after, new[identity])
    known = {fill.trade_id for fill in state.fills} | set(
        state.initial_readback.confirmed_trade_ids
    )
    if not set(old) <= known:
        return (), "FEE_PRIOR_TRADES_UNEXPLAINED"
    try:
        order_id = journal.find_ref(row["OrderRef"])
        order = journal.find(order_id)
    except ValueError:
        return (), "FEE_EXTERNAL_TRADE"
    if (
        row["InstrumentID"],
        row["ExchangeID"],
        row["TradingDay"],
        row["Direction"],
        row["OffsetFlag"],
        row["HedgeFlag"],
        row["Volume"],
    ) != (
        order["native"],
        order["exchange"],
        order["trading_day"],
        "0" if order["side"] == "BUY" else "1",
        order["offset"],
        "1",
        1,
    ):
        raise ValueError("FEE_TRADE_ORDER_MISMATCH")

    # No other changed/unknown orders in the fee window may explain the counter.
    def orders(data):
        return {
            (r["FrontID"], r["SessionID"], r["OrderRef"]): r for r in data["orders"]
        }

    o0, o1 = orders(left), orders(right)
    expected = (order["front_id"], order["session_id"], order["order_ref"])
    for key in set(o0) | set(o1):
        if key != expected and o0.get(key) != o1.get(key):
            return (), "FEE_OTHER_ORDER_CHANGED"
    matches = [
        r
        for r in right["orders"]
        if (r["FrontID"], r["SessionID"], r["OrderRef"]) == expected
    ]
    if (
        len(matches) != 1
        or matches[0]["OrderSysID"].strip() != row["OrderSysID"].strip()
        or matches[0]["VolumeTraded"] != 1
    ):
        return (), "FEE_NATIVE_ORDER_NOT_CONFIRMED"
    return (
        Fee(
            identity,
            delta,
            "ctp-commission-delta:"
            + native_hash((before.source_id, after.source_id, identity, str(delta))),
        ),
    ), "ACTUAL_COMMISSION_COUNTER_DELTA"


def performance(baseline, current):
    if baseline.account_id != current.account_id or baseline.at > current.at:
        raise ValueError("PERFORMANCE_BASELINE_MISMATCH")
    f = current.data["funds"][0]
    b = baseline.data["funds"][0]
    equity = number(f["Balance"], True)
    comparable = baseline.trading_day == current.trading_day
    cash = (
        number(f["Deposit"])
        - number(f["Withdraw"])
        - number(b["Deposit"])
        + number(b["Withdraw"])
        if comparable
        else None
    )
    profit = equity - number(b["Balance"], True) - cash if comparable else None
    ratio = (
        profit / number(b["Balance"], True)
        if comparable and number(b["Balance"], True) > 0
        else None
    )
    return Performance(
        current.account_id,
        current.source_id,
        equity,
        number(f["Available"], True),
        number(f["Commission"]),
        number(f["CloseProfit"], True),
        number(f["PositionProfit"], True),
        cash,
        profit,
        ratio,
        "NATIVE_ACCOUNT_INTERVAL" if comparable else "CASHFLOW_CONTINUITY_REQUIRED",
    )
