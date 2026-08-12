import request from './request'
import type {
  DominantContractListResponse,
  MarketBarsPageRequest,
  MarketBarsPageResponse,
  MarketReadState,
  MarketFrequency,
  MarketRadarResponse,
  ProductResearchResponse,
  SeriesKind,
} from '@/types/market'

export function getMarketDominants() {
  return request.get<never, DominantContractListResponse>('/market/dominants')
}

export function getMarketRadar() {
  return request.get<never, MarketRadarResponse>('/market/research/radar')
    .then(normalizeMarketRadar)
}

export function getProductResearch(params: {
  symbol: string
  seriesKind: SeriesKind
  contract?: string
}) {
  return request.get<never, ProductResearchResponse>('/market/research/product', {
    params: {
      symbol: params.symbol,
      series_kind: params.seriesKind,
      contract: params.seriesKind === 'contract' ? params.contract : undefined,
    },
  }).then(normalizeProductResearch)
}

/** FastAPI serializes Decimal as strings; convert only at the display HTTP boundary. */
function normalizeProductResearch(payload: ProductResearchResponse): ProductResearchResponse {
  return {
    ...payload,
    position20: toNumber(payload.position20),
    distance_to_20d_high: toNumber(payload.distance_to_20d_high),
    distance_to_20d_low: toNumber(payload.distance_to_20d_low),
    volume_ratio20: toNumber(payload.volume_ratio20),
    oi_change_1d: toNumber(payload.oi_change_1d),
    turnover_change_5d: toNumber(payload.turnover_change_5d),
    atr14_percentile252: toNumber(payload.atr14_percentile252),
    recent_daily: payload.recent_daily.map((bar) => ({
      ...bar,
      open: Number(bar.open),
      high: Number(bar.high),
      low: Number(bar.low),
      close: Number(bar.close),
      volume: Number(bar.volume),
      turnover: toNumber(bar.turnover),
      open_interest: toNumber(bar.open_interest),
    })),
  }
}

function toNumber(value: number | string | null): number | null {
  return value === null ? null : Number(value)
}

function normalizeMarketRadar(payload: MarketRadarResponse): MarketRadarResponse {
  return {
    ...payload,
    items: payload.items.map(normalizeRadarItem),
    attention: payload.attention.map(normalizeRadarItem),
    sector_summary: payload.sector_summary.map((sector) => ({
      ...sector,
      median_price_change_1d: toNumber(sector.median_price_change_1d),
    })),
  }
}

function normalizeRadarItem(item: MarketRadarResponse['items'][number]) {
  return {
    ...item,
    price_change_1d: toNumber(item.price_change_1d),
    price_change_5d: toNumber(item.price_change_5d),
    volume_ratio20: toNumber(item.volume_ratio20),
    oi_change_1d: toNumber(item.oi_change_1d),
    atr14_percentile252: toNumber(item.atr14_percentile252),
    position20: toNumber(item.position20),
    turnover: toNumber(item.turnover),
  }
}

export function getMarketBarsPage(params: MarketBarsPageRequest) {
  return request.get<never, MarketBarsPageResponse>('/market/bars/page', { params })
}

export interface MarketStateRequest {
  seriesKind: SeriesKind
  symbol: string
  contract?: string
  frequency: MarketFrequency
}

export function getMarketState(params: MarketStateRequest) {
  return request.get<never, MarketReadState>('/market/state', {
    params: {
      series_kind: params.seriesKind,
      symbol: params.symbol,
      contract: params.seriesKind === 'contract' ? params.contract : undefined,
      frequency: params.frequency,
    },
  })
}
