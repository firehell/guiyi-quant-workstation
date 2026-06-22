import request from './request'
import type { BarData, SymbolInfo } from '@/types/market'

/** 获取合约列表 */
export function getSymbols(exchange?: string) {
  return request.get<any, SymbolInfo[]>('/api/symbols', { params: { exchange } })
}

/** 获取K线数据 */
export function getKlines(params: {
  symbol: string
  period: string
  start?: string
  end?: string
}) {
  return request.get<any, BarData[]>('/api/klines', { params })
}

/** 获取最新行情快照 */
export function getQuote(symbol: string) {
  return request.get<any, SymbolInfo>(`/api/quote/${symbol}`)
}
