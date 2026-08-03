import request from './request'
import type { BacktestReport, BacktestTrade } from '@/types/backtest'
import type {
  BacktestMarketBarsQueryDebug,
  BacktestMarketBarsResult,
  BarData,
  DataProfileSummary,
  DominantContractListResponse,
  LiveMarketBarsResponse,
  MarketMacdIndicatorResponse,
  MarketBarsRequestParams,
  MarketBarsResponse,
  MarketIndicatorsResponse,
  MarketWorkbenchCoverage,
  SymbolInfo,
} from '@/types/market'
import type { MainIndicatorRequestParams } from '@/utils/mainIndicators'
import {
  toCanonicalBarsRequest,
  toCanonicalIndicatorsRequest,
  toCanonicalReportBarsQuery,
} from '@/utils/dataCoreV2Market'

interface BacktestKlineQueryOptions {
  limit?: number
  preferTradeWindow?: boolean
  paddingDays?: number
}

/** 获取合约列表 */
export function getSymbols(exchange?: string) {
  return request.get<any, SymbolInfo[]>('/api/symbols', { params: { exchange } })
}

/** 获取K线数据 */
export function getKlines(params: {
  symbol: string
  contract: string
  period: string
  start?: string
  end?: string
  limit?: number
}) {
  return request.get<any, BarData[]>('/api/klines', { params })
}

/** 获取主力/可报价合约列表 */
export function getMarketDominants(params?: {
  exchange?: string
  quote_ready?: boolean
  search?: string
}) {
  return request.get<any, DominantContractListResponse>('/market/dominants', { params })
}

export interface MarketWorkbenchCoverageParams {
  symbol?: string
  contract?: string
  period?: string
  include_paths?: boolean
  summary?: boolean
}

/** 获取 K线工作台可展示 coverage */
export function getMarketWorkbenchCoverage(params?: MarketWorkbenchCoverageParams) {
  return request.get<any, MarketWorkbenchCoverage>('/market/workbench/coverage', { params })
}

/** 获取 Data Core V2 Catalog coverage，不读取 legacy Profile/Binding。 */
export function getCanonicalMarketCoverage(symbol = 'jm') {
  return request.get<any, MarketWorkbenchCoverage>('/market/coverage/canonical', {
    params: { symbol },
  })
}

/** 获取 K线工作台 bars 和质量摘要 */
export function getMarketBars(params: MarketBarsRequestParams) {
  return request.get<any, MarketBarsResponse>('/market/bars/canonical', {
    params: toCanonicalBarsRequest(params),
  })
}

/** 获取 K 线叠加指标序列 */
export function getMarketIndicators(params: MainIndicatorRequestParams) {
  return request.get<any, MarketIndicatorsResponse>('/market/indicators/canonical', {
    params: toCanonicalIndicatorsRequest(params),
  })
}

/** 获取 MACD 指标（Web 兼容策略 web_macd_legacy_v1） */
export function getMarketMacdIndicator(params: MarketBarsRequestParams & { policy?: 'web_macd_legacy_v1' }) {
  return request.get<any, MarketMacdIndicatorResponse>('/market/indicators/macd/canonical', {
    params: toCanonicalBarsRequest(params),
  })
}

/** 获取实时行情 coverage */
export function getLiveMarketCoverage(params?: MarketWorkbenchCoverageParams) {
  return request.get<any, MarketWorkbenchCoverage>('/market/live/coverage', { params })
}

/** 获取实时行情 K 线 bars */
export function getLiveMarketBars(params: {
  symbol: string
  contract: string
  period: string
  start?: string
  end?: string
  provider?: string | null
  source_mode?: string | null
  limit?: number
}) {
  return request.get<any, LiveMarketBarsResponse>('/market/live/bars', { params })
}

/** 获取实时订阅目标合约列表 */
export function getLiveTargets() {
  return request.get<any, import('@/types/market').LiveTargetContractsResponse>('/market/live/targets')
}

/** 获取数据 profile 摘要列表 */
export function getDataProfiles() {
  return request.get<any, DataProfileSummary[]>('/data/profiles')
}

/** Use only the report's frozen canonical identity; legacy report fields stay display-only. */
export function normalizeMarketQueryFromReport(
  report: BacktestReport,
  _trades: BacktestTrade[],
  _options: BacktestKlineQueryOptions = {},
): BacktestMarketBarsQueryDebug {
  return toCanonicalReportBarsQuery(report)
}

/** Read report bars once from the exact immutable canonical input identity. */
export async function getMarketBarsForBacktestReport(
  report: BacktestReport,
  trades: BacktestTrade[],
  options: BacktestKlineQueryOptions = {},
): Promise<BacktestMarketBarsResult> {
  const query = normalizeMarketQueryFromReport(report, trades, options)
  const response = await getMarketBars(query.attempted[0])
  return { response, query }
}

/** @deprecated 后端暂无 /api/quote，请使用 dominants / bars API */
export function getQuote(_symbol: string) {
  return Promise.reject(new Error('quote API is not available; use getMarketDominants or getMarketBars'))
}
