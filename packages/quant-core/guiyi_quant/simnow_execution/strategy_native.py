"""Native event Session proofs for ordinary strategy execution, without I/O."""

from datetime import datetime
from zoneinfo import ZoneInfo

from .inventory import linked_trade, native_order


def validate_strategy_events(snapshot, authority, journal, state):
    """Resolve each event's own product/physical contract/day, including old closes.

    ``authority(product, trading_day, raw_time, physical_contract)`` is the
    existing read-only MarketBridge/PortfolioMarket seam, never a new resolver.
    No comparison is made between the broker clock and the client clock.
    """
    orders = {order.order_id: order for order in state.orders}
    checked = set()
    for kind, date_field, time_field in (
        ("orders", "InsertDate", "InsertTime"),
        ("trades", "TradeDate", "TradeTime"),
    ):
        for row in snapshot.data[kind]:
            if kind == "orders":
                order_id = native_order(row, journal)
            else:
                linked = linked_trade(snapshot, row)
                order_id = journal.find_ref(linked["OrderRef"])
            order = orders.get(order_id)
            if order is None:
                raise ValueError("NATIVE_EVENT_OWNERSHIP_UNPROVEN")
            raw = datetime.strptime(row[date_field] + row[time_field], "%Y%m%d%H:%M:%S").replace(
                tzinfo=ZoneInfo("Asia/Shanghai")
            )
            day = datetime.strptime(row["TradingDay"], "%Y%m%d").date()
            key = order.product, order.contract, day, raw, row["ExchangeID"]
            if key in checked:
                continue
            proof = authority(order.product, day, raw, order.contract)
            if (
                proof.contract != order.contract or proof.exchange != row["ExchangeID"]
                or proof.session.contract != order.contract or not proof.session.can_trade
            ):
                raise ValueError("NATIVE_EVENT_SESSION_UNPROVEN")
            checked.add(key)
