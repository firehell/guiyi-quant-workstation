/** K线/Bar 数据 */
export interface BarData {
  time: string
  open: number
  high: number
  low: number
  close: number
  volume: number
  openInterest?: number
  turnover?: number
}

/** 合约信息 */
export interface SymbolInfo {
  symbol: string
  name: string
  exchange: string
  productType: 'futures' | 'options' | 'stock'
  multiplier: number
  marginRatio: number
  tickSize: number
  tradingHours: string
}

/** 行情快照 */
export interface QuoteSnapshot {
  symbol: string
  lastPrice: number
  bidPrice: number
  askPrice: number
  bidVolume: number
  askVolume: number
  volume: number
  openInterest: number
  turnover: number
  preClose: number
  preSettle: number
  timestamp: string
}
