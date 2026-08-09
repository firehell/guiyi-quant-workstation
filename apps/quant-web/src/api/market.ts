import request from './request'
import type {
  DominantContractListResponse,
  MarketBarsPageRequest,
  MarketBarsPageResponse,
  MarketBarsRequestParams,
  MarketBarsResponse,
  MarketCoverageResponse,
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
