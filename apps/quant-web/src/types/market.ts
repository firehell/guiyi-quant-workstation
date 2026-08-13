export const MARKET_FREQUENCIES = ['1m', '5m', '15m', '30m', '60m', '1d', '1w'] as const
export type MarketFrequency = (typeof MARKET_FREQUENCIES)[number]
export type SeriesKind = 'continuous' | 'actual_dominant' | 'contract'

export interface DominantContractItem {
  product: string
  product_name: string
  sector: string
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

export interface ResolvedContractSegment {
  contract: string
  start_trading_day: string
  end_trading_day: string
}

export interface MarketBarsPageRequest {
  series_kind: SeriesKind
  symbol: string
  contract?: string
  frequency: MarketFrequency
  before?: string
  limit?: number
}

export interface MarketPageMeta {
  has_more_before: boolean
  next_before: string | null
}

export interface MarketBarsPageResponse {
  request: {
    series_kind: SeriesKind
    symbol: string
    contract: string | null
    frequency: MarketFrequency
    before: string | null
    limit: number
  }
  bars: CanonicalBarDto[]
  canonical_coverage: { start: string; end: string } | null
  page: MarketPageMeta
  resolved_contract_segments: ResolvedContractSegment[]
}

/** Read-only Product Research snapshot; nullable backend metrics stay nullable in the browser. */
export interface ProductResearchResponse {
  symbol: string
  product_name: string
  sector: string
  exchange: string
  series_kind: SeriesKind
  contract: string | null
  as_of: string
  current_dominant: string
  dominant_mapping_date: string
  daily_trend: 'up' | 'down' | 'neutral' | 'unavailable'
  weekly_trend: 'up' | 'down' | 'neutral' | 'unavailable'
  position20: number | null
  distance_to_20d_high: number | null
  distance_to_20d_low: number | null
  volume_ratio20: number | null
  oi_change_1d: number | null
  turnover_change_5d: number | null
  atr14_percentile252: number | null
  recent_daily: CanonicalBarDto[]
}

export interface MarketRadarSummary {
  up_count: number
  down_count: number
  volume_expansion_count: number
  oi_increase_count: number
  high_volatility_count: number
}

export interface MarketRadarItem {
  symbol: string
  product_name: string
  sector: string
  price_change_1d: number | null
  price_change_5d: number | null
  volume_ratio20: number | null
  oi_change_1d: number | null
  atr14_percentile252: number | null
  position20: number | null
  turnover: number | null
  reason_codes: string[]
}

export interface MarketRadarSectorSummary {
  sector: string
  total_count: number
  participant_count: number
  up_count: number
  down_count: number
  median_price_change_1d: number | null
  attention_count: number
}

export interface MarketRadarResponse {
  status: 'ready' | 'degraded'
  expected_as_of: string
  active_count: number
  participant_count: number
  stale: string[]
  unavailable: string[]
  summary: MarketRadarSummary
  items: MarketRadarItem[]
  attention: MarketRadarItem[]
  sector_summary: MarketRadarSectorSummary[]
}

/** 后端 `/market/state` 与 WebSocket `state` 事件的只读展示状态。 */
export interface MarketReadState {
  symbol: string
  series_kind: SeriesKind
  frequency: MarketFrequency
  operational: boolean
  phase: 'TRADING' | 'BREAK' | 'CLOSED' | 'UNKNOWN'
  trading_day: string | null
  live_eligible: boolean
  live_available: boolean
  live_contract: string | null
  canonical_end: string | null
  after_market: Record<string, unknown>
}

export type MarketWsMessage =
  | { type: 'state'; state: MarketReadState }
  | { type: 'snapshot'; bars: CanonicalBarDto[] }
  | { type: 'bar'; bar: CanonicalBarDto }
  | { type: 'reset'; trading_day: string | null; contract: string | null }

export interface KlineMarker {
  id: string
  time: string
  label: string
  tooltip?: string
  color: string
  position: 'aboveBar' | 'belowBar' | 'inBar'
  shape: 'circle' | 'square' | 'arrowUp' | 'arrowDown'
}

export interface AlertEvent {
  id: number
  rule_code: string
  symbol: string
  contract: string
  frequency: '15m'
  bar_end: string
  observation_types: Array<'buy' | 'sell'>
  detected_at: string
  notified_at: string
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
