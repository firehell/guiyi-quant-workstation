"""Translate explicitly selected CTP fields with stable cabinet identities."""

from collections import Counter
from datetime import datetime
from decimal import Decimal, InvalidOperation
import re
from zoneinfo import ZoneInfo

from app.simulation_center.readback import ReadbackError

EXCHANGES = {"SHFE", "INE", "DCE", "CZCE", "CFFEX", "GFEX"}
DIRECTIONS = {"0": "LONG", "1": "SHORT"}
OFFSETS = {"0": "OPEN", "1": "CLOSE", "3": "CLOSETODAY", "4": "CLOSEYESTERDAY"}
SHANGHAI = ZoneInfo("Asia/Shanghai")


def _require(condition):
    if not condition:
        raise ReadbackError("NATIVE_FACT_CONFLICT")


def _amount(value, *, positive=False):
    number = Decimal(str(value))
    _require(number.is_finite() and abs(number) < Decimal("1e20") and (not positive or number > 0))
    return format(number, "f")


def _lots(value):
    _require(type(value) is int and value >= 0)
    return value


def _native_id(value):
    value = value.strip()
    _require(re.fullmatch(r"[0-9A-Za-z_-]{1,32}", value) is not None)
    return value


def _instrument(row):
    exchange = row["ExchangeID"]
    contract = row["InstrumentID"].upper()
    _require(exchange in EXCHANGES and re.fullmatch(r"[A-Z]{1,8}[0-9]{3,4}", contract) is not None)
    return {"exchange": exchange, "contract": contract}


def _identity(row, investor, day, *, account=False, position=False):
    _require(row["BrokerID"].strip() == "9999"
             and row["AccountID" if account else "InvestorID"].strip() == investor)
    # Native position reads lack an independent epoch when bound to the active request.
    if not position or row.get("TradingDay"):
        _require(row["TradingDay"] == day)


def _unique(rows):
    result = {}
    for row in rows:
        _require(row["id"] not in result)
        result[row["id"]] = row
    return list(result.values())


def normalize(sections: dict, investor: str, day: str) -> dict:
    try:
        return _normalize(sections, investor, day)
    except (AttributeError, InvalidOperation, KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, ReadbackError):
            raise
        raise ReadbackError("NATIVE_FACT_INVALID") from None


def _normalize(sections, investor, day):
    trading_day = datetime.strptime(day, "%Y%m%d").date().isoformat()
    (account,) = sections["account"]
    _identity(account, investor, day, account=True)
    _require(account["CurrencyID"] == "CNY")
    balances = {key: _amount(account[native]) for key, native in {
        "equity": "Balance", "available": "Available", "margin": "CurrMargin",
        "deposits": "Deposit", "withdrawals": "Withdraw",
    }.items()}

    positions = []
    for row in sections["positions"]:
        _identity(row, investor, day, position=True)
        instrument = _instrument(row)
        direction = {"2": "LONG", "3": "SHORT"}[row["PosiDirection"]]
        quantity = _lots(row["Position"])
        if instrument["exchange"] in {"SHFE", "INE"}:
            # These venues separate today and history into distinct rows.
            today = {"1": quantity, "2": 0}[row["PositionDate"]]
        else:
            today = _lots(row["TodayPosition"])
        frozen = _lots(row["ShortFrozen" if direction == "LONG" else "LongFrozen"])
        _require(today <= quantity and frozen <= quantity)
        hedge = _native_id(row["HedgeFlag"])
        period = _native_id(row["PositionDate"])
        positions.append({
            **instrument, "id": f'{instrument["exchange"]}:{instrument["contract"]}:{direction}:{hedge}:{period}',
            "direction": direction, "quantity": quantity, "today": today, "yesterday": quantity - today,
            "frozen": frozen, "hedge_flag": hedge, "pnl": _amount(row["PositionProfit"]),
        })

    orders = []
    system_orders = {}
    for row in sections["orders"]:
        _identity(row, investor, day)
        instrument = _instrument(row)
        exchange = instrument["exchange"]
        system = row["OrderSysID"].strip()
        front, session, reference = row["FrontID"], row["SessionID"], _native_id(row["OrderRef"])
        _require(type(front) is int and type(session) is int)
        order_id = f"{trading_day}:{exchange}:{front}:{session}:{reference}"
        if system:
            system = _native_id(system)
            _require((exchange, system) not in system_orders)
            system_orders[exchange, system] = order_id
        quantity, filled = _lots(row["VolumeTotalOriginal"]), _lots(row["VolumeTraded"])
        status = row["OrderStatus"]
        _require(status in {"0", "1", "2", "3", "4", "5", "a", "b", "c"} and quantity > 0 and filled <= quantity)
        if status == "0":
            _require(filled == quantity)
        elif status in {"1", "2"}:
            _require(0 < filled < quantity)
        elif status in {"3", "4", "b"}:
            _require(filled == 0)
        orders.append({
            **instrument, "id": order_id, "system_id": system or None, "direction": DIRECTIONS[row["Direction"]],
            "offset": OFFSETS[row["CombOffsetFlag"]], "quantity": quantity, "filled": filled,
            "price": _amount(row["LimitPrice"]), "status": status,
        })

    order_by_id = {order["id"]: order for order in _unique(orders)}
    fills = []
    quantities = Counter()
    for row in sections["fills"]:
        _identity(row, investor, day)
        instrument = _instrument(row)
        exchange = instrument["exchange"]
        order_id = system_orders[exchange, _native_id(row["OrderSysID"])]
        order = order_by_id[order_id]
        quantity = _lots(row["Volume"])
        direction, offset = DIRECTIONS[row["Direction"]], OFFSETS[row["OffsetFlag"]]
        _require(quantity > 0 and (order["contract"], order["direction"], order["offset"])
                 == (instrument["contract"], direction, offset))
        quantities[order_id] += quantity
        _require(re.fullmatch(r"[0-9]{8}", row["TradeDate"]))
        _require(re.fullmatch(r"[0-9]{2}:[0-9]{2}:[0-9]{2}", row["TradeTime"]))
        time = datetime.strptime(row["TradeDate"] + row["TradeTime"], "%Y%m%d%H:%M:%S").replace(tzinfo=SHANGHAI)
        fills.append({
            **instrument, "id": f'{trading_day}:{exchange}:{_native_id(row["TradeID"])}', "order_id": order_id,
            "direction": direction, "offset": offset, "quantity": quantity, "price": _amount(row["Price"], positive=True),
            "occurred_at": time.isoformat(), "fee": None,
        })

    _require(all(order["filled"] == quantities[order["id"]] for order in orders))
    return {
        "trading_day": trading_day, "account": {**balances, "currency": "CNY"},
        "positions": _unique(positions), "orders": orders, "fills": _unique(fills),
    }
