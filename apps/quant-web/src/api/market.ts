import request from './request'
import { createConditionalHomeRead } from './homeConditionalRead'
import { READ_PRIORITY } from '../utils/readAdmission.ts'
import type {
  DominantContractListResponse,
  MarketProductDirectoryResponse,
  MarketBarsPageRequest,
  MarketBarsPageWireResponse,
  MarketFrequency,
  MarketReadState,
  ProductResearchResponse,
  SeriesKind,
} from '@/types/market'
import { normalizeMarketHomeOverviewResponse } from '@/utils/marketHomeTypes'
import { normalizeMarketBarsPageResponse } from './marketWire.ts'

export { normalizeMarketBarsPageResponse } from './marketWire.ts'

export function normalizeHomeDirectory(value: unknown): DominantContractListResponse {
  const body = value as DominantContractListResponse
  if (!body || !Array.isArray(body.items) || body.items.some(item => !item || typeof item.product !== 'string' || typeof item.product_name !== 'string')) throw new Error('INVALID_HOME_DIRECTORY')
  return body
}
export const getMarketDominants = createConditionalHomeRead('/market/dominants', normalizeHomeDirectory)

export function normalizeMarketProductDirectory(value: unknown): MarketProductDirectoryResponse {
  const body = value as MarketProductDirectoryResponse
  if (!body || !Array.isArray(body.items) || !body.items.length || body.items.some(item =>
    !item || typeof item.product !== 'string' || !item.product.trim()
    || typeof item.product_name !== 'string' || !item.product_name.trim()
    || typeof item.exchange !== 'string' || !item.exchange.trim()
    || typeof item.sector !== 'string' || !item.sector.trim()
    || 'actual_contract' in item || 'dominant_mapping_date' in item)
    || new Set(body.items.map(item => item.product)).size !== body.items.length) throw new Error('INVALID_PRODUCT_DIRECTORY')
  return body
}
export const getMarketProductDirectory = createConditionalHomeRead('/market/product-directory', normalizeMarketProductDirectory)

export const getMarketHomeOverview = createConditionalHomeRead('/market/research/home-overview', normalizeMarketHomeOverviewResponse)

export function getProductResearch(params: { symbol: string; seriesKind: SeriesKind; contract?: string }) {
  return request.get<never, ProductResearchResponse>('/market/research/product', {
    params: {
      symbol: params.symbol,
      series_kind: params.seriesKind,
      contract: params.seriesKind === 'contract' ? params.contract : undefined,
    },
  }).then((payload) => ({
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
      open: Number(bar.open), high: Number(bar.high), low: Number(bar.low),
      close: Number(bar.close), volume: Number(bar.volume),
      turnover: toNumber(bar.turnover), open_interest: toNumber(bar.open_interest),
    })),
  }))
}

function toNumber(value: number | string | null): number | null {
  return value === null ? null : Number(value)
}

export function getMarketBarsPage(params: MarketBarsPageRequest, signal?: AbortSignal) {
  return request.get<never, MarketBarsPageWireResponse>('/market/bars/page', {
    params, signal, readPriority: params.before ? READ_PRIORITY.history : READ_PRIORITY.foreground,
  })
    .then(normalizeMarketBarsPageResponse)
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
