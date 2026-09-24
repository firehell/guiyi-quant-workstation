"""Provider-free replay of one pinned current-day RQData response capture."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from app.market_data.metadata import MetadataSnapshot
from app.market_data.rqdata_adapter import RQDataClient


class _FrozenFutures:
    def __init__(self, owner: _FrozenApi) -> None:
        self.owner = owner

    def get_dominant(
        self, symbol: str, *, start_date: date, end_date: date,
        rule: int, rank: int,
    ) -> list[dict[str, Any]]:
        self.owner.expect("get_dominant")
        if (
            symbol not in self.owner.dominants
            or symbol in self.owner.seen_symbols
            or start_date != self.owner.day
            or end_date != self.owner.next_day
            or rule != 2 or rank != 1
        ):
            raise ValueError("FROZEN_DOMINANT_REQUEST_INVALID")
        self.owner.seen_symbols.add(symbol)
        return self.owner.dominants[symbol]


class _FrozenApi:
    """Only the five methods used by current_day_metadata_snapshot exist."""

    def __init__(self, source: dict[str, Any], day: date) -> None:
        self.source = source
        self.day = day
        self.next_day = next(
            date.fromisoformat(value)
            for value in source["source_trading_dates"][0]
            if date.fromisoformat(value) > day
        )
        self.calendar_end = date.fromisoformat(source["calendar_end"])
        self.calls = 0
        self.dominants = source["source_dominants"]
        self.seen_symbols: set[str] = set()
        self.futures = _FrozenFutures(self)

    def expect(self, method: str) -> None:
        expected = self.source["provider_calls"]
        if self.calls >= len(expected) or expected[self.calls] != method:
            raise ValueError("FROZEN_CALL_ORDER_INVALID")
        self.calls += 1

    def get_trading_dates(self, *, start_date: date, end_date: date) -> list[str]:
        index = self.calls
        self.expect("get_trading_dates")
        if start_date != self.day:
            raise ValueError("FROZEN_CALENDAR_REQUEST_INVALID")
        if index == 0 and end_date == self.day + timedelta(days=14):
            return self.source["source_trading_dates"][0]
        if index == 2 and end_date == self.calendar_end:
            return self.source["source_trading_dates"][1]
        raise ValueError("FROZEN_CALENDAR_REQUEST_INVALID")

    def all_instruments(self, *, type: str) -> list[dict[str, Any]]:
        self.expect("all_instruments")
        if type != "Future":
            raise ValueError("FROZEN_INVENTORY_REQUEST_INVALID")
        return self.source["source_instruments"]

    def get_trading_periods(
        self, contracts: tuple[str, ...], *, start_date: date,
        end_date: date, frequency: str,
    ) -> list[dict[str, Any]]:
        self.expect("get_trading_periods")
        if (
            contracts != tuple(sorted(self.source["requested_contracts"]))
            or start_date != self.day
            or end_date != self.calendar_end
            or frequency != "1m"
        ):
            raise ValueError("FROZEN_PERIOD_REQUEST_INVALID")
        return self.source["source_periods"]


def frozen_snapshot(
    source: dict[str, Any], products: tuple[str, ...], trading_day: date,
) -> MetadataSnapshot:
    """Run the published adapter normalization against captured responses only."""
    api = _FrozenApi(source, trading_day)
    client = object.__new__(RQDataClient)
    client.api = api
    snapshot = client.current_day_metadata_snapshot(products, trading_day)
    summary = source["snapshot_summary"]
    if (
        api.calls != source["provider_call_count"]
        or api.seen_symbols != {product.upper() for product in products}
        or len(snapshot.calendars) != summary["calendar_rows"]
        or len(snapshot.sessions) != summary["session_rows"]
        or len(snapshot.main_contracts) != summary["rank1_rows"]
    ):
        raise ValueError("FROZEN_SOURCE_REPLAY_MISMATCH")
    return snapshot
