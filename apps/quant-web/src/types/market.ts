/** K线/Bar 数据 */
export interface BarData {
  time: string
  datetime?: string
  trading_day?: string
  symbol?: string
  contract?: string
  exchange?: string
  open: number
  high: number
  low: number
  close: number
  volume: number
  openInterest?: number
  turnover?: number
}

export interface KlineMarker {
  id: string
  time: string
  label: string
  tooltip?: string
  color: string
  position: 'aboveBar' | 'belowBar' | 'inBar'
  shape: 'circle' | 'square' | 'arrowUp' | 'arrowDown'
}

export type IndicatorPanelType = 'macd' | 'atr' | 'volume_ratio' | 'signal_score'

export interface ChartOverlay {
  id: string
  type: 'price_line' | 'signal_marker' | 'trade_marker' | 'risk_band'
  price?: number
  label: string
  color: string
  lineStyle?: 'solid' | 'dashed' | 'dotted'
}

export interface HoverKlineContext {
  time: string
  bar: BarData
  ema21?: number | null
  macd?: {
    dif?: number | null
    dea?: number | null
    histogram?: number | null
  } | null
  atr?: number | null
  marker?: KlineMarker | null
}

export interface MarketCoveragePeriod {
  period: string
  provider: string
  data_type: string
  start_time: string
  end_time: string
  row_count: number
  quality_status: string
}

export interface MarketCoverageContract {
  contract: string
  name?: string | null
  exchange?: string | null
  provider?: string | null
  status?: string | null
  periods: MarketCoveragePeriod[]
}

export interface MarketCoverageInstrument {
  symbol: string
  name?: string | null
  exchange?: string | null
  sector?: string | null
  contracts: MarketCoverageContract[]
}

export interface MarketCoverageItem {
  symbol: string
  contract: string
  period: string
  provider: string
  data_type: string
  exchange?: string | null
  name?: string | null
  start_time: string
  end_time: string
  row_count: number
  quality_status: string
}

export interface MarketWorkbenchSelection {
  symbol: string
  contract: string
  period: string
  provider?: string | null
  start: string
  end: string
}

export interface MarketWorkbenchCoverage {
  instruments: MarketCoverageInstrument[]
  items: MarketCoverageItem[]
  default_selection?: MarketWorkbenchSelection | null
}

export interface MarketBarsQuality {
  status: string
  missing_bars: number
  duplicated_bars: number
  abnormal_price_count: number
  abnormal_volume_count: number
  report_count: number
}

export interface MarketBarsCoverage {
  symbol: string
  contract: string
  period: string
  provider?: string | null
  data_type?: string | null
  start_time?: string | null
  end_time?: string | null
  row_count: number
  quality_status: string
}

export interface MarketBarsResponse {
  bars: BarData[]
  quality: MarketBarsQuality
  coverage?: MarketBarsCoverage | null
  request: {
    symbol: string
    contract: string
    period: string
    start?: string | null
    end?: string | null
    provider?: string | null
    data_role?: string | null
    limit: number
  }
  message?: string | null
}

export interface MarketBarsRequestParams {
  symbol: string
  contract: string
  period: string
  start?: string
  end?: string
  provider?: string | null
  data_role?: string | null
  limit?: number
}

export interface BacktestMarketBarsQueryDebug {
  symbol: string
  vt_symbol?: string | null
  contract: string
  exchange?: string | null
  interval: string
  start?: string
  end?: string
  provider?: string | null
  data_role?: string | null
  attempted: MarketBarsRequestParams[]
}

export interface BacktestMarketBarsResult {
  response: MarketBarsResponse
  query: BacktestMarketBarsQueryDebug
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
