"""Full-universe, read-only Market Radar composed from MarketDataService daily bars."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from statistics import median
from typing import Callable, Literal, Mapping

from app.market_data.domain import BarFrequency, SeriesKind, SeriesPageQuery
from app.market_data.market_data_service import MarketDataError, MarketDataService
from app.market_data.product_taxonomy import ProductTaxonomyEntry
from app.market_data.research_metrics import ResearchMetrics, calculate_research_metrics

PRICE_MOVE_PCT = Decimal("0.02")
VOLUME_EXPANSION_RATIO = Decimal("1.50")
OI_EXPANSION_PCT = Decimal("0.05")
HIGH_VOLATILITY_PERCENTILE = Decimal("0.80")
NEAR_HIGH_POSITION = Decimal("0.90")
NEAR_LOW_POSITION = Decimal("0.10")
ATTENTION_MIN_REASONS = 2
ATTENTION_LIMIT = 10
RADAR_DAILY_LIMIT = 300


@dataclass(frozen=True, slots=True)
class RadarItem:
    symbol: str
    product_name: str
    sector: str
    metrics: ResearchMetrics
    turnover: Decimal | None
    reason_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RadarSectorSummary:
    sector: str
    total_count: int
    participant_count: int
    up_count: int
    down_count: int
    median_price_change_1d: Decimal | None
    attention_count: int


@dataclass(frozen=True, slots=True)
class MarketRadarSnapshot:
    status: Literal["ready", "degraded"]
    expected_as_of: date
    active_count: int
    participant_count: int
    stale: tuple[str, ...]
    unavailable: tuple[str, ...]
    items: tuple[RadarItem, ...]
    attention: tuple[RadarItem, ...]
    sector_summary: tuple[RadarSectorSummary, ...]


class MarketRadarService:
    """Strictly read-only full-universe radar; no provider, Redis, scheduler or mutation dependency."""

    def __init__(
        self,
        market_data: MarketDataService,
        *,
        products: tuple[str, ...],
        taxonomy: Mapping[str, ProductTaxonomyEntry],
        latest_complete_day: Callable[[tuple[str, ...]], date],
    ) -> None:
        self._market_data = market_data
        self._products = products
        self._taxonomy = taxonomy
        self._latest_complete_day = latest_complete_day

    def snapshot(self) -> MarketRadarSnapshot:
        expected = self._latest_complete_day(self._products)
        items: list[RadarItem] = []
        stale: list[str] = []
        unavailable: list[str] = []
        for symbol in self._products:
            try:
                daily = self._market_data.query_page(
                    SeriesPageQuery(
                        SeriesKind.ACTUAL_DOMINANT,
                        symbol,
                        BarFrequency.D1,
                        limit=RADAR_DAILY_LIMIT,
                    )
                ).bars
            except MarketDataError:
                unavailable.append(symbol)
                continue
            if not daily or daily[-1].trading_day != expected:
                stale.append(symbol)
                continue
            metrics = calculate_research_metrics(daily, ())
            item = RadarItem(
                symbol,
                self._taxonomy[symbol].name,
                self._taxonomy[symbol].sector,
                metrics,
                daily[-1].turnover,
                (),
            )
            items.append(
                RadarItem(
                    item.symbol,
                    item.product_name,
                    item.sector,
                    item.metrics,
                    item.turnover,
                    _reason_codes(item),
                )
            )
        attention = tuple(
            sorted(
                (
                    item
                    for item in items
                    if len(item.reason_codes) >= ATTENTION_MIN_REASONS
                ),
                key=_attention_sort_key,
            )[:ATTENTION_LIMIT]
        )
        attention_symbols = {item.symbol for item in attention}
        sectors = tuple(_sector_summaries(self._products, self._taxonomy, items, attention_symbols))
        return MarketRadarSnapshot(
            "ready" if len(items) == len(self._products) else "degraded",
            expected,
            len(self._products),
            len(items),
            tuple(stale),
            tuple(unavailable),
            tuple(items),
            attention,
            sectors,
        )


def _reason_codes(item: RadarItem) -> tuple[str, ...]:
    metrics = item.metrics
    reasons: list[str] = []
    if metrics.price_change_1d is not None:
        if metrics.price_change_1d >= PRICE_MOVE_PCT:
            reasons.append("price_move_up")
        if metrics.price_change_1d <= -PRICE_MOVE_PCT:
            reasons.append("price_move_down")
    if (
        metrics.volume_ratio20 is not None
        and metrics.volume_ratio20 >= VOLUME_EXPANSION_RATIO
    ):
        reasons.append("volume_expansion")
    if metrics.oi_change_1d is not None:
        if metrics.oi_change_1d >= OI_EXPANSION_PCT:
            reasons.append("oi_increase")
        if metrics.oi_change_1d <= -OI_EXPANSION_PCT:
            reasons.append("oi_decrease")
    if (
        metrics.atr14_percentile252 is not None
        and metrics.atr14_percentile252 >= HIGH_VOLATILITY_PERCENTILE
    ):
        reasons.append("high_volatility")
    if metrics.position20 is not None:
        if metrics.position20 >= NEAR_HIGH_POSITION:
            reasons.append("near_20d_high")
        if metrics.position20 <= NEAR_LOW_POSITION:
            reasons.append("near_20d_low")
    if metrics.daily_trend == "up":
        reasons.append("ema21_up")
    if metrics.daily_trend == "down":
        reasons.append("ema21_down")
    return tuple(reasons)


def _attention_sort_key(item: RadarItem) -> tuple[Decimal, Decimal, Decimal, str]:
    return (
        -Decimal(len(item.reason_codes)),
        -(
            abs(item.metrics.price_change_1d)
            if item.metrics.price_change_1d is not None
            else Decimal("-1")
        ),
        -(item.turnover if item.turnover is not None else Decimal("-1")),
        item.symbol,
    )


def _sector_summaries(
    products: tuple[str, ...],
    taxonomy: Mapping[str, ProductTaxonomyEntry],
    items: list[RadarItem],
    attention_symbols: set[str],
):
    by_symbol = {item.symbol: item for item in items}
    for sector in sorted({entry.sector for entry in taxonomy.values()}):
        sector_products = [symbol for symbol in products if taxonomy[symbol].sector == sector]
        participants = [by_symbol[symbol] for symbol in sector_products if symbol in by_symbol]
        changes = [item.metrics.price_change_1d for item in participants if item.metrics.price_change_1d is not None]
        yield RadarSectorSummary(
            sector,
            len(sector_products),
            len(participants),
            sum(
                item.metrics.price_change_1d is not None
                and item.metrics.price_change_1d > 0
                for item in participants
            ),
            sum(
                item.metrics.price_change_1d is not None
                and item.metrics.price_change_1d < 0
                for item in participants
            ),
            Decimal(str(median(changes))) if changes else None,
            sum(item.symbol in attention_symbols for item in participants),
        )
