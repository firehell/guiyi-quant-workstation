import request from './request'
import type {
  DominantContractListResponse,
  MarketBarsPageRequest,
  MarketBarsPageResponse,
  MarketBarsRequestParams,
  MarketBarsResponse,
  MarketCoverageResponse,
  MarketReadState,
  MarketFrequency,
  SeriesKind,
} from '@/types/market'

export function getMarketDominants() {
  return request.get<never, DominantContractListResponse>('/market/dominants')
}

export function getCanonicalMarketCoverage(symbol?: string) {
  return request.get<never, MarketCoverageResponse>('/market/coverage/canonical', {
    params: symbol ? { symbol } : undefined,
  })
}

export function getMarketBars(params: MarketBarsRequestParams) {
  return request.get<never, MarketBarsResponse>('/market/bars/canonical', { params })
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
