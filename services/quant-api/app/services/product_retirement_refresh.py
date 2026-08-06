"""Build the fixed direct-data refresh targets for the retained universe.

Identity expansion is owned by ``data_operations.target_planner``. This module
keeps the retirement executor boundary during M1-A and delegates target building.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Callable, Protocol, Sequence

from app.data_core.catalog import CanonicalMainContractMapping
from app.data_core.product_retirement import assert_products_active
from app.data_core.rqdata_adapter import MainMapRequest, MainMapRow
from app.services.data_operations.target_planner import (
    DERIVED_FREQUENCIES as _PLANNER_DERIVED,
    DIRECT_FREQUENCIES as _PLANNER_DIRECT,
    build_identity_targets,
)


DIRECT_FREQUENCIES = tuple(item.value for item in _PLANNER_DIRECT)
DERIVED_FREQUENCIES = tuple(item.value for item in _PLANNER_DERIVED)


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
    """A calendar-derived refresh window (legacy retirement executor)."""

    start_day: date
    end_day: date
    start: datetime
    end: datetime
    weekly_end_day: date | None = None

    def __post_init__(self) -> None:
        if (
            self.start_day > self.end_day
            or self.start.tzinfo is None
            or self.end.tzinfo is None
            or self.start >= self.end
            or (
                self.weekly_end_day is not None
                and not self.start_day <= self.weekly_end_day <= self.end_day
            )
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
    ) -> dict[str, object]:
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
                weekly_end_day=window.weekly_end_day,
            )
            for target in targets:
                self._sync_direct_target(target)
            refreshed[symbol] = targets
        self._direct_targets = refreshed
        return {
            "status": "passed",
            "product_count": len(active),
            "target_count": sum(len(items) for items in refreshed.values()),
            "frequencies": list(DIRECT_FREQUENCIES),
        }

    def aggregate(
        self, products: tuple[str, ...], frequencies: tuple[str, ...]
    ) -> dict[str, object]:
        if frequencies != DERIVED_FREQUENCIES:
            raise ValueError("PRODUCT_RETIREMENT_REFRESH_FREQUENCIES_INVALID")
        active = assert_products_active(products)
        if tuple(self._direct_targets) != active:
            raise ValueError("PRODUCT_RETIREMENT_REFRESH_DIRECT_PHASE_REQUIRED")
        target_count = 0
        for symbol in active:
            for direct_target in self._direct_targets[symbol]:
                if direct_target.frequency != "1m":
                    continue
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
                    target_count += 1
        return {
            "status": "passed",
            "product_count": len(active),
            "target_count": target_count,
            "source_frequency": "1m",
            "frequencies": list(DERIVED_FREQUENCIES),
        }


def build_refresh_targets(
    *,
    products: Sequence[str],
    mappings: Sequence[CanonicalMainContractMapping],
    start: datetime,
    end: datetime,
    weekly_end_day: date | None = None,
) -> tuple[RefreshTarget, ...]:
    """Thin adapter over the shared identity planner (no parallel planning semantics)."""
    active = assert_products_active(products)
    targets = build_identity_targets(
        products=active,
        mappings=mappings,
        start=start,
        end=end,
        weekly_end_day=weekly_end_day,
    )
    return tuple(
        RefreshTarget(
            dataset_kind=item.dataset_kind.value,
            symbol=item.symbol,
            contract_or_series=item.contract_or_series,
            frequency=item.frequency.value,
            start=item.start,
            end=item.end,
        )
        for item in targets
    )
