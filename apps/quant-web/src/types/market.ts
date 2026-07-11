export interface DominantBarsCoveragePeriod {
  available: boolean
  start_time?: string | null
  end_time?: string | null
  row_count: number
  quality_status: string
}

export interface DominantContractItem {
  product: string
  product_name: string
  exchange?: string | null
  exchange_name?: string | null
  sector?: string | null
  category?: string | null
  is_active?: boolean
  continuous_contract: string
  actual_contract: string
  dominant_mapping_date: string
  bars_coverage: Record<string, DominantBarsCoveragePeriod>
  quote_ready: boolean
  default_period: string
}

export interface DominantContractListResponse {
  items: DominantContractItem[]
  default_quote_period: string
}

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
  bar_status?: string
  quality_status?: string
  source_mode?: string
  revision?: number
  source_bar_count?: number
  expected_bar_count?: number
  quality_reasons?: string[]
  source_start_datetime?: string | null
  source_end_datetime?: string | null
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
export type MainIndicatorId = 'ema10' | 'ema21' | 'ema60' | 'huo_tian_da_you'
export type MainIndicatorHoverValues = Record<string, number | null>

export type MainIndicatorId = 'ema_10' | 'ema_21' | 'ema_60' | 'htdy'

export interface MainIndicatorDefinition {
  id: MainIndicatorId
  name: string
  displayName: string
  pane: 'main'
  renderer: 'line' | 'markers' | 'band' | 'mixed'
  defaultVisible: boolean
  color: string
  parameters: Record<string, number | string | boolean>
  lookbackBars: number
  alertCapable: boolean
  available: boolean
  unavailableReason?: string
}

export interface MainIndicatorValue {
  id: MainIndicatorId
  displayName: string
  value: number | null
  color: string
  ready?: boolean
  valid?: boolean
  reason?: string | null
}

export interface MainIndicatorPoint {
  time: string
  value: number | null
  ready: boolean
  valid: boolean
  reason?: string | null
}

export interface MainIndicatorSeries {
  id: MainIndicatorId
  indicator_code: string
  display_name: string
  indicator_version: string
  parameters: Record<string, number | string | boolean>
  parameters_hash: string
  warmup_bars: number
  calculation_source: string
  repainting_risk: string
  points: MainIndicatorPoint[]
}

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
  mainIndicators?: Partial<Record<MainIndicatorId, MainIndicatorHoverValues>>
  ema21?: number | null
  mainIndicators?: MainIndicatorValue[]
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
  source_mode?: string | null
  view_role?: string | null
  continuous_contract?: string | null
  actual_contract?: string | null
  start_time: string
  end_time: string
  latest_bar_time?: string | null
  row_count: number
  quality_status: string
  data_version?: string | null
  data_role?: string | null
  file_path?: string | null
}

export interface MarketCoverageContract {
  contract: string
  name?: string | null
  exchange?: string | null
  provider?: string | null
  status?: string | null
  view_role?: string | null
  continuous_contract?: string | null
  actual_contract?: string | null
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
  source_mode?: string | null
  view_role?: string | null
  continuous_contract?: string | null
  actual_contract?: string | null
  exchange?: string | null
  name?: string | null
  start_time: string
  end_time: string
  latest_bar_time?: string | null
  row_count: number
  quality_status: string
  data_version?: string | null
  data_role?: string | null
  file_path?: string | null
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

export interface LiveMarketBarsQuality {
  status: string
  row_count: number
  chart_row_count: number
  passed_count: number
  warning_count: number
  failed_count: number
  rejected_count: number
  partial_count: number
}

export interface MarketBarsCoverage {
  symbol: string
  contract: string
  period: string
  provider?: string | null
  data_type?: string | null
  source_mode?: string | null
  view_role?: string | null
  continuous_contract?: string | null
  actual_contract?: string | null
  start_time?: string | null
  end_time?: string | null
  latest_bar_time?: string | null
  row_count: number
  quality_status: string
  data_version?: string | null
  data_role?: string | null
  file_path?: string | null
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

export interface MarketIndicatorsResponse {
  request: {
    symbol: string
    contract: string
    period: string
    indicator_codes: string[]
    display_start?: string | null
    display_end?: string | null
    display_bar_count: number
    provider?: string | null
    data_role?: string | null
    quote_mode: boolean
    allow_continuous: boolean
    read_limit: number
  }
  warmup: {
    requested_display_bar_count: number
    max_warmup_bars: number
    read_limit: number
    source_bar_count: number
    display_bar_count: number
  }
  indicators: MainIndicatorSeries[]
  message?: string | null
}

export interface LiveMarketBarsResponse {
  bars: BarData[]
  quality: LiveMarketBarsQuality
  coverage?: MarketBarsCoverage | null
  request: {
    symbol: string
    contract: string
    period: string
    start?: string | null
    end?: string | null
    provider?: string | null
    source_mode?: string | null
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
  quote_mode?: boolean
  allow_continuous?: boolean
  tail?: boolean
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

export interface LiveTargetCoveragePeriod {
  available: boolean
  row_count?: number
  latest_bar_time?: string | null
  quality_status?: string | null
  data_role?: string | null
}

export interface LiveTargetContractItem {
  product: string
  continuous_contract: string
  actual_contract?: string | null
  dominant_mapping_date?: string | null
  readiness_status: string
  blocked_reasons: string[]
  historical_coverage: Record<string, LiveTargetCoveragePeriod>
  live_coverage: Record<string, LiveTargetCoveragePeriod>
  trading_parameter_gate?: Record<string, unknown>
}

export interface LiveTargetContractsResponse {
  provider: string
  target_products: string[]
  trade_date?: string | null
  readiness_status: string
  preview_only: boolean
  writes_strategy_signal: boolean
  writes_signal_event: boolean
  sends_notification: boolean
  auto_order: boolean
  items: LiveTargetContractItem[]
}
