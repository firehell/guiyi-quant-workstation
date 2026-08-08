export const MARKET_FREQUENCIES = ['1m', '5m', '15m', '30m', '60m', '1d', '1w'] as const
export type MarketFrequency = (typeof MARKET_FREQUENCIES)[number]
export type SeriesKind = 'continuous' | 'actual_dominant' | 'contract'

export interface DominantContractItem {
  product: string
  product_name: string
  exchange: string
  actual_contract: string
  dominant_mapping_date: string
}

export interface DominantContractListResponse {
  items: DominantContractItem[]
}

export interface CanonicalBarDto {
  bar_end: string
  trading_day: string
  open: number
  high: number
  low: number
  close: number
  volume: number
  turnover: number | null
  open_interest: number | null
}

/** Lightweight Charts and local indicator input. */
export interface BarData {
  time: string
  trading_day?: string
  open: number
  high: number
  low: number
  close: number
  volume: number
  turnover?: number
  openInterest?: number
}

export interface DatasetIdentity {
  kind: 'continuous' | 'contract'
  symbol: string
  series_or_contract: string
  frequency: MarketFrequency
}

export interface PartitionDigest {
  dataset: DatasetIdentity
  year: number
  month: number
  checksum: string
  manifest_digest: string
}

export interface ResolvedContractSegment {
  contract: string
  start_trading_day: string
  end_trading_day: string
}

export interface MarketBarsRequestParams {
  series_kind: SeriesKind
  symbol: string
  contract?: string
  frequency: MarketFrequency
  start: string
  end: string
}

export interface MarketBarsResponse {
  request: MarketBarsRequestParams
  bars: CanonicalBarDto[]
  coverage: { start: string; end: string } | null
  partition_digests: PartitionDigest[]
  resolved_contract_segments: ResolvedContractSegment[]
  main_map_digest: string | null
}

export interface MarketCoverageItem {
  kind: 'continuous' | 'contract'
  symbol: string
  series_or_contract: string
  frequency: MarketFrequency
  start: string
  end: string
  row_count: number
  partition_count: number
}

export interface MarketCoverageResponse {
  items: MarketCoverageItem[]
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

export interface ChartOverlay {
  id: string
  type: 'price_line' | 'signal_marker' | 'trade_marker' | 'risk_band'
  price?: number
  label: string
  color: string
  lineStyle?: 'solid' | 'dashed' | 'dotted'
}

export type IndicatorPanelType = 'macd' | 'atr' | 'volume_ratio' | 'signal_score'
export type MainIndicatorId = 'ema_10' | 'ema_21' | 'ema_60' | 'htdy'

export interface MainIndicatorDefinition {
  id: MainIndicatorId
  name: string
  displayName: string
  pane: 'main'
  renderer: 'line' | 'markers' | 'band' | 'mixed'
  capability: 'standard_overlay' | 'observation_overlay'
  defaultVisible: boolean
  color: string
  parameters: Record<string, number | string | boolean>
  lookbackBars: number
  alertCapable: boolean
  available: boolean
  repaintingRisk?: 'none' | 'known'
  riskMessages?: string[]
  unstableTailBars?: number
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
  seed_policy: string
  calculation_start?: string | null
  warmup_bars: number
  confirmed_only: boolean
  calculation_source: string
  repainting_risk: string
  points: MainIndicatorPoint[]
}

export interface HoverKlineContext {
  time: string
  bar: BarData
  mainIndicators?: MainIndicatorValue[]
  macd?: { dif?: number | null; dea?: number | null; histogram?: number | null } | null
  atr?: number | null
  marker?: KlineMarker | null
  cursorPrice?: number | null
}
