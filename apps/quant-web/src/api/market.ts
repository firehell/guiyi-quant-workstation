import request from './request'
import type { BarData, MarketBarsResponse, MarketWorkbenchCoverage, SymbolInfo } from '@/types/market'

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
  return request.get<any, MarketWorkbenchCoverage>('/api/v1/market/workbench/coverage')
}

/** 获取 K线工作台 bars 和质量摘要 */
export function getMarketBars(params: {
  symbol: string
  contract: string
  period: string
  start?: string
  end?: string
  provider?: string | null
  data_role?: string | null
  limit?: number
}) {
  return request.get<any, MarketBarsResponse>('/api/v1/market/bars', { params })
}

/** 获取最新行情快照 */
export function getQuote(symbol: string) {
  return request.get<any, SymbolInfo>(`/api/quote/${symbol}`)
}
