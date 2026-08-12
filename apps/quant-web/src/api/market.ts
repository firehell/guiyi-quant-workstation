import request from './request'
import type {
  DominantContractListResponse,
  MarketBarsPageRequest,
  MarketBarsPageResponse,
  MarketReadState,
  MarketFrequency,
  ProductResearchResponse,
  SeriesKind,
} from '@/types/market'

export function getMarketDominants() {
  return request.get<never, DominantContractListResponse>('/market/dominants')
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
  })
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
