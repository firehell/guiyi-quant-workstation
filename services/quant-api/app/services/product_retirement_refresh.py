"""Build the fixed direct-data refresh targets for the retained universe."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Callable, Protocol, Sequence

from app.data_core.catalog import CanonicalMainContractMapping
from app.data_core.product_retirement import assert_products_active
from app.data_core.rqdata_adapter import MainMapRequest, MainMapRow


DIRECT_FREQUENCIES = ("1m", "1d", "1w")
DERIVED_FREQUENCIES = ("5m", "15m", "30m", "60m")


@dataclass(frozen=True)
class RefreshTarget:
    dataset_kind: str
    symbol: str
    contract_or_series: str
    frequency: str
    start: datetime
    end: datetime


@dataclass(frozen=True)
class RefreshWindow:
    """A calendar-derived, exact ten-trading-day refresh window."""

    start_day: date
    end_day: date
    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        if (
            self.start_day > self.end_day
            or self.start.tzinfo is None
            or self.end.tzinfo is None
            or self.start >= self.end
        ):
            raise ValueError("PRODUCT_RETIREMENT_REFRESH_WINDOW_INVALID")


class _MappingAdapter(Protocol):
    def fetch_rank1_map(self, request: MainMapRequest) -> Sequence[MainMapRow]: ...


class RetainedUniverseRefreshExecutor:
    """Run the approved retained-data refresh without exposing generic writes."""

    def __init__(
        self,
        *,
        mapping_window: Callable[[str], RefreshWindow | None],
        mapping_adapter: _MappingAdapter,
        replace_mapping: Callable[[str, date, date, Sequence[MainMapRow]], object],
        list_mappings: Callable[
            [str, date, date], Sequence[CanonicalMainContractMapping]
        ],
        sync_direct_target: Callable[[RefreshTarget], None],
        aggregate_target: Callable[[RefreshTarget], None],
    ) -> None:
        self._mapping_window = mapping_window
        self._mapping_adapter = mapping_adapter
        self._replace_mapping = replace_mapping
        self._list_mappings = list_mappings
        self._sync_direct_target = sync_direct_target
        self._aggregate_target = aggregate_target
        self._direct_targets: dict[str, tuple[RefreshTarget, ...]] = {}

    def sync_direct(
        self, products: tuple[str, ...], frequencies: tuple[str, ...]
    ) -> None:
        if frequencies != DIRECT_FREQUENCIES:
            raise ValueError("PRODUCT_RETIREMENT_REFRESH_FREQUENCIES_INVALID")
        active = assert_products_active(products)
        refreshed: dict[str, tuple[RefreshTarget, ...]] = {}
        for symbol in active:
            window = self._mapping_window(symbol)
            if window is None:
                raise ValueError("PRODUCT_RETIREMENT_REFRESH_WINDOW_MISSING")
            rows = tuple(
                self._mapping_adapter.fetch_rank1_map(
                    MainMapRequest(
                        symbol=symbol,
                        start_day=window.start_day,
                        end_day=window.end_day,
                    )
                )
            )
            if not rows:
                raise ValueError("PRODUCT_RETIREMENT_REFRESH_MAPPING_EMPTY")
            self._replace_mapping(symbol, window.start_day, window.end_day, rows)
            mappings = self._list_mappings(symbol, window.start_day, window.end_day)
            targets = build_refresh_targets(
                products=(symbol,),
                mappings=mappings,
                start=window.start,
                end=window.end,
            )
            for target in targets:
                self._sync_direct_target(target)
            refreshed[symbol] = targets
        self._direct_targets = refreshed

    def aggregate(
        self, products: tuple[str, ...], frequencies: tuple[str, ...]
    ) -> None:
        if frequencies != DERIVED_FREQUENCIES:
            raise ValueError("PRODUCT_RETIREMENT_REFRESH_FREQUENCIES_INVALID")
        active = assert_products_active(products)
        if tuple(self._direct_targets) != active:
            raise ValueError("PRODUCT_RETIREMENT_REFRESH_DIRECT_PHASE_REQUIRED")
        for symbol in active:
            for direct_target in self._direct_targets[symbol]:
                for frequency in DERIVED_FREQUENCIES:
                    self._aggregate_target(
                        RefreshTarget(
                            dataset_kind=direct_target.dataset_kind,
                            symbol=direct_target.symbol,
                            contract_or_series=direct_target.contract_or_series,
                            frequency=frequency,
                            start=direct_target.start,
                            end=direct_target.end,
                        )
                    )


def build_refresh_targets(
    *,
    products: Sequence[str],
    mappings: Sequence[CanonicalMainContractMapping],
    start: datetime,
    end: datetime,
) -> tuple[RefreshTarget, ...]:
    active = assert_products_active(products)
    if start.tzinfo is None or end.tzinfo is None or start >= end:
        raise ValueError("PRODUCT_RETIREMENT_REFRESH_WINDOW_INVALID")
    mapping_by_symbol: dict[str, set[str]] = {symbol: set() for symbol in active}
    for row in mappings:
        if row.symbol not in mapping_by_symbol:
            raise ValueError("PRODUCT_RETIREMENT_REFRESH_MAPPING_OUTSIDE_UNIVERSE")
        mapping_by_symbol[row.symbol].add(row.actual_contract)
    missing = tuple(
        symbol for symbol, contracts in mapping_by_symbol.items() if not contracts
    )
    if missing:
        raise ValueError(
            "PRODUCT_RETIREMENT_REFRESH_MAPPING_MISSING:" + ",".join(missing)
        )
    targets: list[RefreshTarget] = []
    for symbol in active:
        for frequency in DIRECT_FREQUENCIES:
            targets.append(
                RefreshTarget(
                    "continuous",
                    symbol,
                    f"{symbol.upper()}.MAIN",
                    frequency,
                    start,
                    end,
                )
            )
        for contract in sorted(mapping_by_symbol[symbol]):
            for frequency in DIRECT_FREQUENCIES:
                targets.append(
                    RefreshTarget(
                        "actual_dominant", symbol, contract, frequency, start, end
                    )
                )
    return tuple(targets)
