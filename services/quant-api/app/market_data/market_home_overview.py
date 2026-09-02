"""Read-only completed D1/W1 overview for the Market home page."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from statistics import median
from typing import Literal

from app.market_data.domain import BarFrequency, CanonicalBar, SeriesKind, SeriesPageQuery
from app.market_data.errors import InfrastructureError
from app.market_data.market_data_service import (
    DominantContractSummary,
    MarketDataError,
    MarketDataService,
)
from app.market_data.product_retirement import normalize_symbol
from app.market_data.product_taxonomy import ProductTaxonomyEntry
from app.market_data.research_metrics import Trend, calculate_research_metrics


MarketHomeStatus = Literal["ready", "degraded"]
MarketHomeFreshness = Literal["fresh", "stale", "unavailable"]


class MarketHomeOverviewError(RuntimeError):
    """Public-safe failure for a structurally invalid Market Home snapshot."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class MarketHomeItem:
    symbol: str
    product_name: str
    sector: str
    exchange: str
    actual_contract: str
    dominant_mapping_date: date
    data_as_of: date
    close: Decimal
    price_change_1d: Decimal | None
    price_change_5d: Decimal | None
    volume_ratio20: Decimal | None
    oi_change_1d: Decimal | None
    atr14_percentile252: Decimal | None
    daily_trend: Trend
    weekly_trend: Trend
    reason_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MarketHomeSummary:
    price_up_count: int
    price_down_count: int
    price_flat_count: int
    daily_up_count: int
    daily_down_count: int
    daily_neutral_count: int
    daily_unavailable_count: int
    aligned_up_count: int
    aligned_down_count: int


@dataclass(frozen=True, slots=True)
class MarketHomeSectorSummary:
    sector: str
    active_count: int
    participant_count: int
    median_price_change_1d: Decimal | None


@dataclass(frozen=True, slots=True)
class MarketHomeOverviewSnapshot:
    status: MarketHomeStatus
    target_as_of: date
    data_as_of: date
    freshness: MarketHomeFreshness
    active_count: int
    participant_count: int
    stale_count: int
    unavailable_count: int
    summary: MarketHomeSummary
    items: tuple[MarketHomeItem, ...]
    sectors: tuple[MarketHomeSectorSummary, ...]


class MarketHomeOverviewService:
    """Build one completed D1/W1 read snapshot without external side effects."""

    def __init__(
        self,
        *,
        market_data: MarketDataService,
        products: tuple[str, ...],
        taxonomy: Mapping[str, ProductTaxonomyEntry],
        latest_complete_day: Callable[[tuple[str, ...]], date],
    ) -> None:
        normalized_products = _validated_products(products)
        normalized_taxonomy = dict(taxonomy)
        if set(normalized_taxonomy) != set(normalized_products):
            raise MarketHomeOverviewError("MARKET_HOME_TAXONOMY_INVALID")
        self._market_data = market_data
        self._products = normalized_products
        self._taxonomy = normalized_taxonomy
        self._latest_complete_day = latest_complete_day

    def snapshot(self) -> MarketHomeOverviewSnapshot:
        try:
            target_as_of = self._latest_complete_day(self._products)
        except InfrastructureError as exc:
            raise MarketHomeOverviewError(
                "MARKET_HOME_TARGET_AS_OF_UNAVAILABLE"
            ) from exc
        dominants = _dominants_by_symbol(
            self._market_data.list_latest_dominants(), self._products
        )

        items: list[MarketHomeItem] = []
        stale_count = 0
        unavailable_count = 0
        for symbol in self._products:
            daily = _query_through_target(
                self._market_data,
                symbol=symbol,
                frequency=BarFrequency.D1,
                limit=300,
                target_as_of=target_as_of,
            )
            weekly = _query_through_target(
                self._market_data,
                symbol=symbol,
                frequency=BarFrequency.W1,
                limit=80,
                target_as_of=target_as_of,
            )
            if not daily:
                unavailable_count += 1
                continue
            if daily[-1].trading_day != target_as_of:
                stale_count += 1
                continue
            metrics = calculate_research_metrics(daily, weekly)
            dominant = dominants[symbol]
            taxonomy = self._taxonomy[symbol]
            items.append(
                MarketHomeItem(
                    symbol=symbol,
                    product_name=taxonomy.name,
                    sector=taxonomy.sector,
                    exchange=dominant.exchange,
                    actual_contract=dominant.actual_contract,
                    dominant_mapping_date=dominant.dominant_mapping_date,
                    data_as_of=target_as_of,
                    close=daily[-1].close,
                    price_change_1d=metrics.price_change_1d,
                    price_change_5d=metrics.price_change_5d,
                    volume_ratio20=metrics.volume_ratio20,
                    oi_change_1d=metrics.oi_change_1d,
                    atr14_percentile252=metrics.atr14_percentile252,
                    daily_trend=metrics.daily_trend,
                    weekly_trend=metrics.weekly_trend,
                    reason_codes=_reason_codes(metrics),
                )
            )

        return MarketHomeOverviewSnapshot(
            status="ready" if not stale_count and not unavailable_count else "degraded",
            target_as_of=target_as_of,
            data_as_of=target_as_of,
            freshness=(
                "unavailable"
                if unavailable_count
                else "stale" if stale_count else "fresh"
            ),
            active_count=len(self._products),
            participant_count=len(items),
            stale_count=stale_count,
            unavailable_count=unavailable_count,
            summary=_summary(items),
            items=tuple(items),
            sectors=_sector_summaries(self._products, self._taxonomy, items),
        )


def _validated_products(products: tuple[str, ...]) -> tuple[str, ...]:
    if not products or any(not isinstance(product, str) for product in products):
        raise MarketHomeOverviewError("MARKET_HOME_UNIVERSE_INVALID")
    normalized = tuple(normalize_symbol(product) for product in products)
    if any(not product for product in normalized) or normalized != products or len(set(normalized)) != len(normalized):
        raise MarketHomeOverviewError("MARKET_HOME_UNIVERSE_INVALID")
    return normalized


def _dominants_by_symbol(
    dominants: tuple[DominantContractSummary, ...], products: tuple[str, ...]
) -> dict[str, DominantContractSummary]:
    result: dict[str, DominantContractSummary] = {}
    for item in dominants:
        if item.symbol not in products or item.symbol in result:
            raise MarketHomeOverviewError("MARKET_HOME_DOMINANT_CONTEXT_INVALID")
        result[item.symbol] = item
    if set(result) != set(products):
        raise MarketHomeOverviewError("MARKET_HOME_DOMINANT_CONTEXT_INVALID")
    return result


def _through_target(
    bars: tuple[CanonicalBar, ...], target_as_of: date
) -> tuple[CanonicalBar, ...]:
    return tuple(bar for bar in bars if bar.trading_day <= target_as_of)


def _query_through_target(
    market_data: MarketDataService,
    *,
    symbol: str,
    frequency: BarFrequency,
    limit: int,
    target_as_of: date,
) -> tuple[CanonicalBar, ...]:
    try:
        result = market_data.query_page(
            SeriesPageQuery(
                series_kind=SeriesKind.ACTUAL_DOMINANT,
                symbol=symbol,
                frequency=frequency,
                limit=limit,
            )
        )
    except MarketDataError as exc:
        if exc.code in {"QUERY_WINDOW_EMPTY", "DATASET_OR_PARTITION_MISSING"}:
            return ()
        raise MarketHomeOverviewError("MARKET_HOME_DATA_INTEGRITY_ERROR") from exc
    return _through_target(result.bars, target_as_of)


def _reason_codes(metrics) -> tuple[str, ...]:
    values: list[str] = []
    if metrics.price_change_1d is not None:
        if metrics.price_change_1d > 0:
            values.append("price_up")
        elif metrics.price_change_1d < 0:
            values.append("price_down")
    if metrics.volume_ratio20 is not None and metrics.volume_ratio20 > 1:
        values.append("volume_expansion")
    if metrics.oi_change_1d is not None:
        if metrics.oi_change_1d > 0:
            values.append("oi_increase")
        elif metrics.oi_change_1d < 0:
            values.append("oi_decrease")
    values.append(f"daily_{metrics.daily_trend}")
    values.append(f"weekly_{metrics.weekly_trend}")
    if metrics.daily_trend == metrics.weekly_trend == "up":
        values.append("periods_aligned_up")
    elif metrics.daily_trend == metrics.weekly_trend == "down":
        values.append("periods_aligned_down")
    return tuple(values)


def _summary(items: list[MarketHomeItem]) -> MarketHomeSummary:
    return MarketHomeSummary(
        price_up_count=sum(item.price_change_1d is not None and item.price_change_1d > 0 for item in items),
        price_down_count=sum(item.price_change_1d is not None and item.price_change_1d < 0 for item in items),
        price_flat_count=sum(item.price_change_1d == 0 for item in items),
        daily_up_count=sum(item.daily_trend == "up" for item in items),
        daily_down_count=sum(item.daily_trend == "down" for item in items),
        daily_neutral_count=sum(item.daily_trend == "neutral" for item in items),
        daily_unavailable_count=sum(item.daily_trend == "unavailable" for item in items),
        aligned_up_count=sum(item.daily_trend == item.weekly_trend == "up" for item in items),
        aligned_down_count=sum(item.daily_trend == item.weekly_trend == "down" for item in items),
    )


def _sector_summaries(
    products: tuple[str, ...],
    taxonomy: Mapping[str, ProductTaxonomyEntry],
    items: list[MarketHomeItem],
) -> tuple[MarketHomeSectorSummary, ...]:
    ordered_sectors = tuple(dict.fromkeys(taxonomy[symbol].sector for symbol in products))
    active_by_sector: dict[str, int] = defaultdict(int)
    participants_by_sector: dict[str, list[MarketHomeItem]] = defaultdict(list)
    for symbol in products:
        active_by_sector[taxonomy[symbol].sector] += 1
    for item in items:
        participants_by_sector[item.sector].append(item)
    return tuple(
        MarketHomeSectorSummary(
            sector=sector,
            active_count=active_by_sector[sector],
            participant_count=len(participants_by_sector[sector]),
            median_price_change_1d=_median_change(participants_by_sector[sector]),
        )
        for sector in ordered_sectors
    )


def _median_change(items: list[MarketHomeItem]) -> Decimal | None:
    values = [item.price_change_1d for item in items if item.price_change_1d is not None]
    return Decimal(str(median(values))) if values else None
