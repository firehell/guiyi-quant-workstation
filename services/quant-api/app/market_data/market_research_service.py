"""Product Workspace 所需的单品种只读研究快照。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from app.market_data.domain import BarFrequency, CanonicalBar, SeriesKind, SeriesPageQuery
from app.market_data.market_data_service import MarketDataError, MarketDataService
from app.market_data.research_metrics import ResearchMetrics, calculate_research_metrics


@dataclass(frozen=True, slots=True)
class ResearchSeriesIdentity:
    """Research API 的图表 identity；复用历史查询的同一契约校验。"""

    symbol: str
    series_kind: SeriesKind
    contract: str | None = None

    def __post_init__(self) -> None:
        request = SeriesPageQuery(
            series_kind=self.series_kind,
            symbol=self.symbol,
            frequency=BarFrequency.D1,
            contract=self.contract,
            limit=300,
        )
        object.__setattr__(self, "symbol", request.symbol)
        object.__setattr__(self, "series_kind", request.series_kind)
        object.__setattr__(self, "contract", request.contract)


@dataclass(frozen=True, slots=True)
class ProductResearchSnapshot:
    """单个图表 identity 的 P0 研究读模型。"""

    symbol: str
    product_name: str
    sector: str
    exchange: str
    series_kind: SeriesKind
    contract: str | None
    as_of: date
    current_dominant: str
    dominant_mapping_date: date
    metrics: ResearchMetrics
    recent_daily: tuple[CanonicalBar, ...]
    metric_contract: str | None


class MarketResearchService:
    """只读组合 MarketDataService 结果，不接触 provider、Redis 或写路径。"""

    def __init__(self, market_data: MarketDataService) -> None:
        self._market_data = market_data

    def product_snapshot(self, identity: ResearchSeriesIdentity) -> ProductResearchSnapshot:
        daily = self._market_data.query_page(
            SeriesPageQuery(
                identity.series_kind,
                identity.symbol,
                BarFrequency.D1,
                limit=300,
                contract=identity.contract,
            )
        ).bars
        weekly = self._market_data.query_page(
            SeriesPageQuery(
                identity.series_kind,
                identity.symbol,
                BarFrequency.W1,
                limit=80,
                contract=identity.contract,
            )
        ).bars
        if not daily:
            raise MarketDataError("QUERY_WINDOW_EMPTY")
        dominant = next(
            (item for item in self._market_data.list_latest_dominants() if item.symbol == identity.symbol),
            None,
        )
        if dominant is None:
            raise MarketDataError("DOMINANT_CONTEXT_MISSING")
        metric_daily, metric_weekly = daily, weekly
        metric_contract = identity.contract
        if identity.series_kind is SeriesKind.ACTUAL_DOMINANT:
            owner = self._market_data.dominant_segment_for_day(
                identity.symbol, daily[-1].trading_day
            )
            metric_contract = owner.contract
            metric_daily = self._market_data.query_physical_bars_as_of(
                symbol=identity.symbol,
                contract=owner.contract,
                frequency=BarFrequency.D1,
                trading_day=daily[-1].trading_day,
                limit=300,
            )
            metric_weekly = self._market_data.query_physical_bars_as_of(
                symbol=identity.symbol,
                contract=owner.contract,
                frequency=BarFrequency.W1,
                trading_day=daily[-1].trading_day,
                limit=80,
            )
        return ProductResearchSnapshot(
            symbol=identity.symbol,
            product_name=dominant.product_name,
            sector=dominant.sector,
            exchange=dominant.exchange,
            series_kind=identity.series_kind,
            contract=identity.contract,
            as_of=daily[-1].trading_day,
            current_dominant=dominant.actual_contract,
            dominant_mapping_date=dominant.dominant_mapping_date,
            metrics=calculate_research_metrics(metric_daily, metric_weekly),
            recent_daily=tuple(daily[-80:]),
            metric_contract=metric_contract,
        )
