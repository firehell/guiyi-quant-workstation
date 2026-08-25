import request from './request'
import type {
  DominantContractListResponse,
  JdjStrategyHistoricalRequest,
  JdjStrategyHistoricalResponse,
  MarketBarsPageRequest,
  MarketBarsPageResponse,
  MainForceMirrorV2PageRequest,
  MainForceMirrorV2PageResponse,
  MainForceMirrorV2PageWireResponse,
  MarketReadState,
  MarketFrequency,
  MarketRadarResponse,
  ProductResearchResponse,
  SeriesKind,
  SubingFrequency,
  SubingHistoricalSignalRequest,
  SubingHistoricalSignalResponse,
  SubingDailyWatchCurrentWireResponse,
  SubingResearchResponse,
} from '@/types/market'
import {
  normalizeMainForceMirrorV2Page,
  normalizeMarketRadar,
  normalizeSubingDailyWatchCurrent,
  normalizeSubingResearch,
} from '@/types/market'

export function getMarketDominants() {
  return request.get<never, DominantContractListResponse>('/market/dominants')
}

export function getMarketRadar() {
  return request.get<never, MarketRadarResponse>('/market/research/radar')
    .then(normalizeMarketRadar)
}

export function getSubingDailyWatchCurrent() {
  return request
    .get<never, SubingDailyWatchCurrentWireResponse>(
      '/market/research/subing-daily-watch/current',
    )
    .then(normalizeSubingDailyWatchCurrent)
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

export function getSubingResearch(params: { symbol: string; frequency: SubingFrequency }) {
  return request.get<never, SubingResearchResponse>('/market/research/subing', {
    params: {
      symbol: params.symbol,
      frequency: params.frequency,
    },
  }).then(normalizeSubingResearch)
}

export function getSubingHistoricalSignals(params: SubingHistoricalSignalRequest) {
  return request.get<never, SubingHistoricalSignalResponse>(
    '/market/research/subing/history',
    { params },
  )
}

export function getJdjStrategyHistoricalActions(params: JdjStrategyHistoricalRequest) {
  return request.get<never, JdjStrategyHistoricalResponse>(
    '/market/research/jdj-strategy/history',
    { params },
  )
}

export function getMainForceMirrorV2Page(params: MainForceMirrorV2PageRequest) {
  return request.get<never, MainForceMirrorV2PageWireResponse>(
    '/market/research/main-force-mirror',
    { params },
  ).then(normalizeMainForceMirrorV2Page) as Promise<MainForceMirrorV2PageResponse>
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
