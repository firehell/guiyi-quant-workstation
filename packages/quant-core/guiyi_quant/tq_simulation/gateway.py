"""Pinned TqSdk 3.10.4 boundary. Only TqKq can be constructed here.

Private SDK fields are confined to completeness and pre-margin source validation;
there is no inferred zero inventory or fallback from failed account margin lookup.
"""

from datetime import datetime, UTC
from decimal import Decimal
from zoneinfo import ZoneInfo
from importlib.metadata import version
from .journal import digest
from .transport import SdkTransport

SHANGHAI = ZoneInfo("Asia/Shanghai")


def decimal(value, *, positive=False):
    if isinstance(value, bool):
        raise ValueError("TQ_NUMBER_INVALID")
    result = Decimal(str(value))
    if not result.is_finite() or positive and result <= 0:
        raise ValueError("TQ_NUMBER_UNAVAILABLE")
    return result


def quantity(value):
    result = decimal(value)
    if result != int(result) or result < 0:
        raise ValueError("TQ_VOLUME_INVALID")
    return int(result)


def instant_ns(value):
    if type(value) is not int or value <= 0:
        raise ValueError("TQ_TIMESTAMP_UNAVAILABLE")
    return datetime.fromtimestamp(value // 1000000000, UTC).replace(
        microsecond=(value % 1000000000) // 1000
    )


def order_status(row):
    total, left = quantity(row["volume_orign"]), quantity(row["volume_left"])
    if left > total:
        raise ValueError("TQ_ORDER_VOLUME_INVALID")
    if total > 0 and left == 0:
        return "FILLED"
    if row.get("is_error") is True:
        return "REJECTED"
    if row.get("status") == "FINISHED" and row.get("is_dead") is True:
        return "CANCELLED"
    if row.get("status") == "ALIVE" and row.get("is_online") is True:
        return "WORKING"
    return "UNKNOWN"


class Gateway:
    def __init__(self, credentials):
        if version("tqsdk") != "3.10.4":
            raise ValueError("TQ_SDK_VERSION_MISMATCH")
        from tqsdk import TqApi, TqAuth, TqKq

        self._transport = SdkTransport()
        self.api = None
        try:
            self.account = TqKq()
            self.api = TqApi(
                account=self.account,
                auth=TqAuth(credentials.username, credentials.password),
                debug=False,
                disable_print=True,
            )
            self._transport.verify(self.api, self.account)
            self.execution_allowed = False
            self.account_id = credentials.account_id
            self.account_key = self.api._account._get_account_key(self.account)
            self.account_ref = self.api.get_account(account=self.account)
            self.positions = self.api.get_position(account=self.account)
            self.orders = self.api.get_order(account=self.account)
            self.trades = self.api.get_trade(account=self.account)
            self.quotes = {}
            self.notifications = set()
            self.connections = {}
            self.last_day = None
            self.reconnection_required = False
            self._connection_events = []
        except BaseException:
            try:
                if self.api is not None:
                    self.api.close()
            finally:
                self._transport.close()
            raise

    def close(self):
        try:
            self.api.close()
        finally:
            self._transport.close()

    def connection_events(self):
        events = tuple(self._connection_events)
        self._connection_events.clear()
        return events

    def update(self, seconds=1):
        import time
        from .maintenance import MaintenanceDisconnect, is_terminal_maintenance

        try:
            self.api.wait_update(deadline=time.time() + seconds)
        except Exception as error:
            if is_terminal_maintenance(error, datetime.now(UTC)):
                self.execution_allowed = False
                self.reconnection_required = True
                raise MaintenanceDisconnect() from None
            raise
        self.refresh_notifications()

    def refresh_notifications(self):
        for key, row in list(self.api._data.get("notify", {}).items()):
            if key in self.notifications:
                continue
            self.notifications.add(key)
            code = row.get("code")
            conn = row.get("conn_id")
            if code in {2019112910, 2019112911, 2019112901, 2019112902}:
                events = getattr(self, "_connection_events", None)
                if events is None:
                    self._connection_events = events = []
                # Never persist notify content, URL, account name or credentials.
                events.append({
                    "code": code,
                    "connection": "md" if conn == "md" else "td" if conn == "td_0" else "other",
                    "at": datetime.now(UTC).isoformat(),
                })
            if code in {2019112910, 2019112911}:
                self.connections[conn] = False
                self.reconnection_required = True
            elif code in {2019112901, 2019112902}:
                self.connections[conn] = True
                if code == 2019112902:
                    self.reconnection_required = True
        if any(v is False for v in self.connections.values()):
            raise ValueError("TQ_DISCONNECTED")

    def snapshot(self, now):
        self.refresh_notifications()
        if self.api._account._get_trade_more_data(self.api._data):
            raise ValueError("TQ_ACCOUNT_INCOMPLETE")
        a = self.account_ref
        fields = (
            "balance",
            "available",
            "margin",
            "frozen_margin",
            "frozen_commission",
            "commission",
            "position_profit",
            "close_profit",
            "static_balance",
            "deposit",
            "withdraw",
        )
        account = {k: str(decimal(a[k])) for k in fields}
        if decimal(account["balance"]) <= 0 or any(
            decimal(account[k]) < 0
            for k in (
                "available",
                "margin",
                "frozen_margin",
                "frozen_commission",
                "commission",
            )
        ):
            raise ValueError("TQ_ACCOUNT_FUNDS_INVALID")
        positions = []
        for symbol, row in list(self.positions.items()):
            if str(symbol).startswith("_"):
                continue
            keys = (
                "pos_long_today",
                "pos_long_his",
                "pos_short_today",
                "pos_short_his",
            )
            amounts = {k: quantity(row.get(k, 0)) for k in keys}
            if sum(amounts.values()):
                positions.append(
                    {
                        "symbol": symbol,
                        **amounts,
                        "frozen_long": quantity(row.get("volume_long_frozen")),
                        "frozen_short": quantity(row.get("volume_short_frozen")),
                    }
                )
        orders = []
        order_fields = (
            "order_id",
            "exchange_order_id",
            "exchange_id",
            "instrument_id",
            "direction",
            "offset",
            "volume_orign",
            "volume_left",
            "status",
            "is_error",
            "is_dead",
            "is_online",
            "insert_date_time",
            "price_type",
        )
        for key, row in list(self.orders.items()):
            if str(key).startswith("_"):
                continue
            item = {k: row.get(k) for k in order_fields}
            try:
                item["limit_price"] = str(decimal(row.get("limit_price")))
            except (ValueError, ArithmeticError):
                item["limit_price"] = None
            item["state"] = order_status(item)
            orders.append(item)
        trades = []
        trade_fields = (
            "order_id",
            "trade_id",
            "exchange_id",
            "instrument_id",
            "direction",
            "offset",
            "volume",
            "trade_date_time",
        )
        for key, row in list(self.trades.items()):
            if str(key).startswith("_"):
                continue
            item = {k: row.get(k) for k in trade_fields}
            item["price"] = str(decimal(row.get("price"), positive=True))
            trades.append(item)
        # OTG servers do not all publish an account trading_day. Absence stays
        # explicit; the execution day is independently proven by RQData Session.
        trade_data = self.api._data.get("trade", {}).get(self.account_key, {})
        day = trade_data.get("trading_day") or a.get("trading_day")
        if isinstance(day, int):
            day = str(day)
        if day is not None:
            if not isinstance(day, str) or len(day) != 8 or not day.isdigit():
                raise ValueError("TQ_TRADING_DAY_INVALID")
            datetime.strptime(day, "%Y%m%d")
        if self.last_day is not None and day is not None and day != self.last_day:
            self.reconnection_required = True
            self.api._requests["margin_rates"].clear()
        if day is not None:
            self.last_day = day
        payload = {
            "account_id": self.account_id,
            "trading_day": day,
            "account": account,
            "positions": sorted(positions, key=lambda x: x["symbol"]),
            "orders": sorted(orders, key=lambda x: x["order_id"]),
            "trades": sorted(trades, key=lambda x: x["trade_id"]),
        }
        return {
            **payload,
            "snapshot_id": digest(payload),
            "observed_at": now.isoformat(),
        }

    def quote(self, symbol):
        if symbol not in self.quotes:
            self.quotes[symbol] = self.api.get_quote(symbol)
        return self.quotes[symbol]

    def margin(self, symbol, direction):
        q = self.quote(symbol)
        user = self.api._account._get_account_id(self.account)
        # The SDK caches a rounded rate, but exposes only one shared raw query
        # slot. Invalidate both so A/B/A and price changes cannot reuse stale
        # account-specific pre-margin. This is only ephemeral query state.
        self.api._requests["margin_rates"].pop(
            (self.account_key, symbol, direction), None
        )
        slots = (
            self.api._data.get("trade", {})
            .get(self.account_key, {})
            .get("pre_insert_orders", {})
        )
        slots.pop(self.account_key + "_" + user, None)
        try:
            self.api._get_margin_rate(q, direction, self.account)
        finally:
            self.refresh_notifications()
        row = (
            self.api._data.get("trade", {})
            .get(self.account_key, {})
            .get("pre_insert_orders", {})
            .get(self.account_key + "_" + user, {})
        )
        exchange, instrument = symbol.split(".", 1)
        if (row.get("exchange_id"), row.get("instrument_id"), row.get("direction")) != (
            exchange,
            instrument,
            direction,
        ):
            raise ValueError("TQ_ACCOUNT_MARGIN_UNAVAILABLE")
        margin = decimal(row.get("pre_margin"), positive=True)
        fee = decimal(row.get("pre_commission", q.get("commission")))
        if fee < 0:
            raise ValueError("TQ_ACCOUNT_FEE_UNAVAILABLE")
        return (
            margin,
            fee,
            {
                "source": "TQKQ_PRE_INSERT",
                "margin": str(margin),
                "fee": str(fee),
                "direction": direction,
            },
        )

    def assert_continuity(self):
        # All synchronous SDK calls may drive wait_update internally. Snapshot
        # also checks native trading-day changes before any transport action.
        self.snapshot(datetime.now(UTC))
        if self.reconnection_required:
            raise ValueError("TQ_RECOVERY_REQUIRED")

    def submit(self, symbol, order, offset, native_id):
        if not self.execution_allowed:
            raise ValueError("TQ_OBSERVE_ONLY")
        self.assert_continuity()
        q = self.quote(symbol)
        price = order.price
        opponent = q["ask_price1"] if order.side == "BUY" else q["bid_price1"]
        if decimal(opponent, positive=True) != price:
            raise ValueError("TQ_OPPONENT_PRICE_DRIFT")
        converted = float(price)
        if decimal(converted) != price or price % decimal(
            q["price_tick"], positive=True
        ):
            raise ValueError("TQ_PRICE_PRECISION_INVALID")
        self.assert_continuity()
        self.api.insert_order(
            symbol=symbol,
            direction=order.side,
            offset=offset,
            volume=1,
            limit_price=converted,
            order_id=native_id,
            account=self.account,
        )

    def cancel(self, native_id):
        if not self.execution_allowed:
            raise ValueError("TQ_OBSERVE_ONLY")
        self.assert_continuity()
        self.api.cancel_order(native_id, account=self.account)
