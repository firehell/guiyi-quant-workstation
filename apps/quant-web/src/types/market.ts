export const MARKET_FREQUENCIES = ['1m', '5m', '15m', '30m', '60m', '1d', '1w'] as const
export type MarketFrequency = (typeof MARKET_FREQUENCIES)[number]
export type SeriesKind = 'continuous' | 'actual_dominant' | 'contract'
export type ResearchOverlayId = 'none' | 'htdy'

export interface ResearchOverlayDefinition {
  id: ResearchOverlayId
  label: string
  supportedSeriesKinds: readonly SeriesKind[]
  supportedFrequencies: readonly MarketFrequency[]
  mainIndicators: readonly MainIndicatorId[]
  historicalSource: 'none' | 'local'
}

export interface DominantContractItem {
  product: string
  product_name: string
  sector: string
  exchange: string
  actual_contract: string
  dominant_mapping_date: string
}

export interface DominantContractListResponse { items: DominantContractItem[] }

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

export interface BarData {
  time: string
  trading_day?: string
  physicalContract?: string
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

export interface MarketPageMeta { has_more_before: boolean; next_before: string | null }

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

export type MarketOverlaySource = 'none' | 'realtime' | 'post_close'
export type MarketWsMessage =
  | { type: 'state'; state: MarketReadState }
  | { type: 'snapshot'; source: MarketOverlaySource; trading_day: string | null; contract: string | null; bars: CanonicalBarDto[] }
  | { type: 'bar'; bar: CanonicalBarDto }
  | { type: 'reset'; trading_day: string | null; contract: string | null }

export interface KlineMarker {
  id: string
  dedupeKey?: string
  time: string
  label: string
  tooltip?: string
  tone: 'up' | 'down' | 'htdy' | 'neutral'
  position: 'aboveBar' | 'belowBar' | 'inBar'
  shape: 'circle' | 'square' | 'arrowUp' | 'arrowDown'
}

interface AlertEventCommon {
  id: number
  symbol: string
  contract: string
  trading_day: string | null
  frequency: MarketFrequency
  bar_end: string
  detected_at: string
  notification_attempted_at: string | null
}

export interface HtdyAlertEvent extends AlertEventCommon {
  rule_code: 'htdy_original_15m'
  result_codes: Array<'buy' | 'sell'>
}

export type AlertEvent = HtdyAlertEvent
export type MainIndicatorId = 'ema_10' | 'ema_21' | 'ema_60' | 'range_detector' | 'htdy'
export type OptionalEmaIndicatorId = 'ema_10' | 'ema_21' | 'ema_60'

export interface MainIndicatorDefinition {
  id: MainIndicatorId
  name: string
  displayName: string
  pane: 'main'
  renderer: 'line' | 'markers' | 'band' | 'mixed'
  capability: 'standard_overlay' | 'observation_overlay'
  defaultVisible: boolean
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
  ready?: boolean
  valid?: boolean
  reason?: string | null
}

export interface HoverKlineContext {
  time: string
  bar: BarData
  mainIndicators?: MainIndicatorValue[]
  rangeDetector?: {
    rangeId: string
    revision: number
    state: 'intact' | 'broken_up' | 'broken_down'
    upper: number
    lower: number
    mid: number
    confirmedAt: string
    visualStartAt: string
  } | null
  macd?: { dif?: number | null; dea?: number | null; histogram?: number | null } | null
  atr?: number | null
  marker?: KlineMarker | null
  cursorPrice?: number | null
}
