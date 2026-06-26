import request from './request'
import type { BarData, MarketBarsResponse, MarketWorkbenchCoverage, SymbolInfo } from '@/types/market'

const apiBaseUrl = (import.meta.env.VITE_API_BASE_URL || '').replace(/\/$/, '')
const apiV1Prefix = apiBaseUrl.endsWith('/api/v1') ? '' : '/api/v1'
const apiV1Path = (path: string) => `${apiV1Prefix}${path}`

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

/** 获取 K线工作台可展示 coverage */
export function getMarketWorkbenchCoverage() {
  return request.get<any, MarketWorkbenchCoverage>(apiV1Path('/market/workbench/coverage'))
}

/** 获取 K线工作台 bars 和质量摘要 */
export function getMarketBars(params: {
  symbol: string
  contract: string
  period: string
  start?: string
  end?: string
  provider?: string | null
  limit?: number
}) {
  return request.get<any, MarketBarsResponse>(apiV1Path('/market/bars'), { params })
}

/** 获取最新行情快照 */
export function getQuote(symbol: string) {
  return request.get<any, SymbolInfo>(`/api/quote/${symbol}`)
}
