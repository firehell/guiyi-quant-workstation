"""Stable two-pass native inventory -> account facts, never a flat-on-error fallback."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
import hashlib
import json
import re
from .. import htdy_execution as h
from .. import htdy_account_execution as a
from ..htdy_account_execution.codec import digest
from .model import Inventory, valid

KINDS = ("funds", "positions", "orders", "trades")


def native_hash(value):
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode()
    ).hexdigest()


def at(value):
    result = datetime.fromisoformat(value)
    if result.tzinfo is None:
        raise ValueError("NATIVE_TIMESTAMP_INVALID")
    return result


def number(value, signed=False):
    # Existing native collector serializes doubles as decimal strings.
    if type(value) is not str:
        raise ValueError("NATIVE_DECIMAL_STRING_REQUIRED")
    result = Decimal(value)
    if (
        not result.is_finite()
        or abs(result) > Decimal("1e30")
        or not signed
        and result < 0
    ):
        raise ValueError("NATIVE_NUMBER_INVALID")
    return result


def quantity(value):
    if type(value) is not int or value < 0:
        raise ValueError("NATIVE_QUANTITY_INVALID")
    return value


@dataclass(frozen=True)
class Snapshot:
    account_id: str
    trading_day: str
    started_at: datetime
    at: datetime
    source_id: str
    payload_json: str

    @property
    def data(self):
        return json.loads(self.payload_json)


def read_snapshot(report, *, now=None):
    try:
        if (
            report["schema"],
            report["environment"],
            report["front"],
            report["source_scope"],
            report["broker_id"],
        ) != (
            "simnow_readonly_inventory_v1",
            "SIMNOW_FIRST",
            "tcp://182.254.243.31:30001",
            "FIRST_ENVIRONMENT_READBACK",
            "9999",
        ):
            raise ValueError("FIRST_ENVIRONMENT_REQUIRED")
        if (
            report["status"] != "READ_ONLY_COMPLETE"
            or report["authentication_passed"] is not True
            or report["login_passed"] is not True
        ):
            raise ValueError("NATIVE_QUERY_INCOMPLETE")
        account, day = report["account_fingerprint"], report["trading_day"]
        if (
            re.fullmatch(r"[a-f0-9]{64}", account) is None
            or re.fullmatch(r"\d{8}", day) is None
        ):
            raise ValueError("NATIVE_IDENTITY_INVALID")
        datetime.strptime(day, "%Y%m%d")
        rounds = report["rounds"]
        if len(rounds) != 2:
            raise ValueError("TWO_NATIVE_ROUNDS_REQUIRED")
        payloads = []
        previous = None
        for index, r in enumerate(rounds, 1):
            start, end = at(r["started_at"]), at(r["completed_at"])
            if (
                r["round"] != index
                or start > end
                or previous is not None
                and start < previous
            ):
                raise ValueError("NATIVE_ROUND_TIME_INVALID")
            previous = end
            if set(r["queries"]) != set(KINDS):
                raise ValueError("NATIVE_QUERY_SET_INVALID")
            payload = {}
            for kind in KINDS:
                q = r["queries"][kind]
                if (
                    q["complete"] is not True
                    or not start <= at(q["started_at"]) <= at(q["completed_at"]) <= end
                    or type(q["rows"]) is not list
                ):
                    raise ValueError("NATIVE_QUERY_INCOMPLETE")
                rows = q["rows"]
                keys = set()
                for row in rows:
                    if row["TradingDay"] != day:
                        raise ValueError("NATIVE_ROW_TRADING_DAY_MISMATCH")
                    if kind == "funds":
                        key = (row["CurrencyID"],)
                    elif kind == "positions":
                        key = tuple(
                            row[k]
                            for k in (
                                "ExchangeID",
                                "InstrumentID",
                                "PosiDirection",
                                "HedgeFlag",
                                "PositionDate",
                            )
                        )
                    elif kind == "orders":
                        key = tuple(
                            row[k] for k in ("FrontID", "SessionID", "OrderRef")
                        )
                    else:
                        key = tuple(
                            row[k]
                            for k in (
                                "ExchangeID",
                                "TradeID",
                                "Direction",
                                "TradingDay",
                            )
                        )
                    if key in keys:
                        raise ValueError("DUPLICATE_NATIVE_ROW")
                    keys.add(key)
                payload[kind] = rows
            if len(payload["funds"]) != 1 or payload["funds"][0]["CurrencyID"] != "CNY":
                raise ValueError("CNY_FUNDS_REQUIRED")
            f = payload["funds"][0]
            for field in (
                "Balance",
                "Available",
                "CurrMargin",
                "FrozenMargin",
                "FrozenCommission",
                "Commission",
                "Deposit",
                "Withdraw",
                "CloseProfit",
                "PositionProfit",
            ):
                number(
                    f[field],
                    signed=field
                    in ("Balance", "Available", "CloseProfit", "PositionProfit"),
                )
            payloads.append(payload)
        if payloads[0] != payloads[1] or report["round_hashes"] != [
            native_hash(p) for p in payloads
        ]:
            raise ValueError("NATIVE_READBACK_CHANGED_OR_HASH_INVALID")
        if now is not None and previous > now:
            raise ValueError("NATIVE_FUTURE_READBACK")
        payload = payloads[1]
        return Snapshot(
            account,
            day,
            at(rounds[0]["started_at"]),
            previous,
            "ctp-inventory:"
            + day
            + ":"
            + native_hash((account, day, payload, rounds[1]["completed_at"])),
            json.dumps(payload, sort_keys=True, separators=(",", ":")),
        )
    except (KeyError, TypeError, ArithmeticError, AttributeError):
        raise ValueError("NATIVE_READBACK_INVALID") from None


def trade_identity(row):
    for k in ("TradingDay", "ExchangeID", "TradeID", "Direction"):
        if type(row[k]) is not str or not row[k].strip():
            raise ValueError("NATIVE_TRADE_ID_INVALID")
    if row["Direction"] not in ("0", "1"):
        raise ValueError("NATIVE_DIRECTION_INVALID")
    return ":".join(
        row[k].strip() for k in ("TradingDay", "ExchangeID", "TradeID", "Direction")
    )


def linked_trade(snapshot, row):
    matches = [
        o
        for o in snapshot.data["orders"]
        if o["ExchangeID"] == row["ExchangeID"]
        and o["OrderSysID"].strip()
        and o["OrderSysID"].strip() == row["OrderSysID"].strip()
    ]
    if len(matches) != 1:
        raise ValueError("NATIVE_TRADE_ORDER_LINK_AMBIGUOUS")
    return {**row, "OrderRef": matches[0]["OrderRef"]}


def order_status(row):
    if row["OrderSubmitStatus"] == "4":
        return "REJECTED"
    if row["OrderStatus"] == "0" and quantity(row["VolumeTraded"]) == 1:
        return "FILLED"
    if row["OrderStatus"] in ("2", "4", "5") and quantity(row["VolumeTraded"]) == 0:
        return "CANCELLED"
    if (
        row["OrderStatus"] == "3"
        and row["OrderSubmitStatus"] == "3"
        and quantity(row["VolumeTraded"]) == 0
    ):
        return "WORKING"
    return "UNKNOWN"


def native_order(row, journal):
    if journal is None:
        return "external:" + digest(
            tuple(
                row.get(k)
                for k in (
                    "TradingDay",
                    "ExchangeID",
                    "FrontID",
                    "SessionID",
                    "OrderRef",
                    "OrderSysID",
                )
            )
        )
    try:
        order_id = journal.find_ref(row["OrderRef"], row["FrontID"], row["SessionID"])
    except ValueError:
        return native_order(row, None)
    bound = journal.find(order_id)
    if (
        row["InstrumentID"],
        row["ExchangeID"],
        row["TradingDay"],
        row["Direction"],
        row["CombOffsetFlag"],
        row["CombHedgeFlag"],
    ) != (
        bound["native"],
        bound["exchange"],
        bound["trading_day"],
        "0" if bound["side"] == "BUY" else "1",
        bound["offset"],
        "1",
    ):
        raise ValueError("NATIVE_ORDER_PROJECTION_IDENTITY")
    if quantity(row["VolumeTotalOriginal"]) != 1 or number(
        row["LimitPrice"]
    ) != Decimal(bound["price"]):
        raise ValueError("NATIVE_ORDER_PROJECTION_SIZE_PRICE")
    systems = {
        p["system_id"]
        for _, p, _ in journal.events()
        if p["kind"] == "order" and p["order_id"] == order_id and p["system_id"]
    }
    if systems and systems != {row["OrderSysID"].strip()}:
        raise ValueError("NATIVE_ORDER_SYSTEM_CONFLICT")
    return order_id


def project_readback(snapshot, bindings, journal, state, valid_until):
    valid_until = min(valid_until, snapshot.at + timedelta(seconds=30))
    valid(snapshot.at, valid_until, snapshot.at)
    if state is not None and state.account_id != snapshot.account_id:
        raise ValueError("NATIVE_ACCOUNT_MISMATCH")
    lookup = {(b.exchange, b.native): b for b in bindings}
    if len(lookup) != len(bindings):
        raise ValueError("DUPLICATE_CONTRACT_BINDING")
    data = snapshot.data
    inventory = []
    positions = []
    products = set()
    grouped = {}
    for row in data["positions"]:
        q = quantity(row["Position"])
        today = quantity(row["TodayPosition"])
        frozen = quantity(row["LongFrozen"]) + quantity(row["ShortFrozen"])
        if not q and not frozen:
            continue
        b = lookup.get((row["ExchangeID"], row["InstrumentID"]))
        if b is None:
            raise ValueError("UNEXPLAINED_NATIVE_POSITION")
        if (
            row["HedgeFlag"] != "1"
            or row["PosiDirection"] not in ("2", "3")
            or row["PositionDate"] not in ("1", "2")
            or today > q
        ):
            raise ValueError("NATIVE_POSITION_DIMENSION_INVALID")
        # SHFE/INE separate today/history rows. Others report aggregate position.
        key = (b.canonical, row["PosiDirection"])
        old = grouped.get(key, (b, 0, 0))
        td = q if row["PositionDate"] == "1" else 0
        if b.exchange not in ("SHFE", "INE"):
            td = today
        grouped[key] = (b, old[1] + td, old[2] + q - td)
        if not q and frozen:
            raise ValueError("FROZEN_POSITION_WITHOUT_HOLDING")
    for (contract, direction), (b, today, yesterday) in grouped.items():
        product = re.match(r"[A-Z]+", contract)[0]
        if product in products or today + yesterday != 1:
            raise ValueError("NATIVE_HEDGE_OR_OVERSIZE_BLOCKED")
        products.add(product)
        side = 1 if direction == "2" else -1
        positions.append(h.Position(product, contract, side))
        inventory.append(
            Inventory(
                contract,
                side,
                today,
                yesterday,
                snapshot.source_id,
                snapshot.at,
                valid_until,
            )
        )
    orders = []
    native_rows = {}
    for row in data["orders"]:
        identity = native_order(row, journal)
        if identity in native_rows:
            raise ValueError("DUPLICATE_LOGICAL_NATIVE_ORDER")
        native_rows[identity] = row
        orders.append(h.OrderReport(identity, order_status(row)))
    trades = tuple(trade_identity(r) for r in data["trades"])
    if len(set(trades)) != len(trades):
        raise ValueError("DUPLICATE_NATIVE_TRADE")
    f = data["funds"][0]
    used, frozen, fee = (
        number(f[k]) for k in ("CurrMargin", "FrozenMargin", "FrozenCommission")
    )
    if (used > 0 and not positions) or (positions and used <= 0):
        raise ValueError("NATIVE_POSITION_MARGIN_UNEXPLAINED")
    if (frozen > 0 or fee > 0) and not any(
        o.status in ("WORKING", "UNKNOWN") for o in orders
    ):
        raise ValueError("NATIVE_FROZEN_WITHOUT_PENDING_ORDER")
    settled = []
    coverage = []
    if state is not None:
        knownfills = {fill.trade_id: fill for fill in state.fills}
        position_match = sorted(positions, key=lambda p: p.product) == sorted(
            state.positions, key=lambda p: p.product
        )
        trades_explained = set(trades) <= set(knownfills) | set(
            state.initial_readback.confirmed_trade_ids
        )
        for order in orders:
            row = native_rows[order.order_id]
            if (
                order.status in ("CANCELLED", "REJECTED")
                and position_match
                and trades_explained
            ):
                if not any(
                    r["ExchangeID"] == row["ExchangeID"]
                    and r["OrderSysID"].strip() == row["OrderSysID"].strip()
                    for r in data["trades"]
                ):
                    settled.append(order.order_id)
        # Only a uniquely attributable sole opening can offset local frozen occupancy.
        active = [
            o for o in orders if o.status not in ("FILLED", "CANCELLED", "REJECTED")
        ]
        if len(active) == 1 and active[0].status == "WORKING":
            identity = active[0].order_id
            reserve = next(
                (
                    r
                    for r in state.reservations
                    if r.order_id == identity and not r.released
                ),
                None,
            )
            if reserve and frozen <= reserve.margin and fee <= reserve.fee:
                coverage.append(a.Coverage(identity, frozen, fee))
    rb = a.Readback(
        h.AccountSnapshot(
            snapshot.account_id,
            snapshot.at,
            number(f["Balance"], True),
            number(f["Available"], True),
            tuple(sorted(positions, key=lambda p: p.product)),
            tuple(orders),
            tuple(settled),
        ),
        used,
        frozen,
        fee,
        tuple(coverage),
        trades,
        snapshot.source_id,
        valid_until,
        True,
    )
    return rb, tuple(inventory)
