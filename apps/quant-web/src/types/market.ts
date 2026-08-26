export const MARKET_FREQUENCIES = ['1m', '5m', '15m', '30m', '60m', '1d', '1w'] as const
export type MarketFrequency = (typeof MARKET_FREQUENCIES)[number]
export type SeriesKind = 'continuous' | 'actual_dominant' | 'contract'
export type ResearchOverlayId = 'none' | 'subing' | 'jdj_strategy' | 'htdy'

export interface ResearchOverlayDefinition {
  id: ResearchOverlayId
  label: string
  supportedSeriesKinds: readonly SeriesKind[]
  supportedFrequencies: readonly MarketFrequency[]
  mainIndicators: readonly MainIndicatorId[]
  historicalSource: 'none' | 'local' | 'subing' | 'jdj_strategy'
}

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

export const SUBING_PUBLIC_FREQUENCIES = ['5m', '15m'] as const
export type SubingFrequency = typeof SUBING_PUBLIC_FREQUENCIES[number]
export type SubingFactorStatus = 'ready' | 'insufficient_data'

export interface SubingFactorSnapshot {
  timeframe: SubingFrequency
  bar_end: string
  trading_day: string
  contract: string
  segment_start_trading_day: string
  bar_source: 'canonical' | 'live'
  close: number
  ema21: number
  price_side: 'above' | 'below' | 'equal' | 'unavailable'
  slope_5_raw: number
  slope_10_raw: number
  slope_5_bps_per_bar: number
  slope_10_bps_per_bar: number
  macd_dif: number
  macd_dea: number
  macd_histogram: number
  macd_cross: 'golden' | 'dead' | 'none' | 'unavailable'
  macd_cross_level: number
  macd_zero_distance_abs: number
  macd_zero_distance_bps: number
  volume: number
  previous_volume: number
  volume_ratio_prev: number | null
}

export interface SubingFactorResult {
  status: SubingFactorStatus
  snapshot: SubingFactorSnapshot | null
}

export type SubingSignalStatus = 'matched' | 'not_matched' | 'research_pending' | 'insufficient_data'
export type SubingSignalDirection = 'long' | 'short' | 'none'
export type SubingConditionState = 'pass' | 'fail' | 'pending' | 'unavailable'

export interface SubingCondition {
  code: string
  state: SubingConditionState
}

export interface SubingSignal {
  status: SubingSignalStatus
  direction: SubingSignalDirection
  trigger_timeframe: SubingFrequency | null
  lower_tf_confirmation: boolean
  resolution: 'higher_timeframe_wins' | 'direction_conflict' | null
  conditions: SubingCondition[]
  error_code: string | null
}

export type SubingLifecycleAvailability = 'ready' | 'unavailable'
export type SubingLifecycleDirection = 'long' | 'short' | 'none'
export type SubingLifecycleStage = 'idle' | 'setup_armed' | 'entry_confirmed' | 'continuation' | 'exit_risk' | 'closed'
export type SubingLifecycleEntryProgress = 'waiting_trigger' | 'hold_confirming' | 'retest_confirming'
export type SubingLifecycleConfirmationSource = 'formal_v1' | 'momentum_hold' | 'pivot_break_hold' | 'pivot_retest_rebreak'
export type SubingLifecyclePivotKind = 'high' | 'low'
export type SubingLifecycleTriggerKind = 'macd_cross' | 'pivot_break'

export interface SubingLifecyclePivot {
  pivot_id: string
  kind: SubingLifecyclePivotKind
  timeframe: '5m'
  pivot_time: string
  confirmed_at: string
  price: number
  contract: string
  segment_start_trading_day: string
}

export interface SubingLifecycleTransition {
  transition_id: string
  transition_at: string
  from_stage: SubingLifecycleStage
  to_stage: SubingLifecycleStage
  reason_codes: string[]
}

export interface SubingLifecycleSnapshot {
  formula_version: string
  policy_id: string
  research_only: boolean
  observed_at: string | null
  anchor_bar_end: string | null
  availability: SubingLifecycleAvailability
  unavailable_reason: string | null
  direction: SubingLifecycleDirection
  stage: SubingLifecycleStage
  opportunity_key: string | null
  entry_progress: SubingLifecycleEntryProgress | null
  trigger_kind: SubingLifecycleTriggerKind | null
  trigger_timeframe: '5m' | '15m' | null
  triggered_at: string | null
  confirmation_source: SubingLifecycleConfirmationSource | null
  confirmed_at: string | null
  hold_count: number
  hold_required: number
  bound_reference_pivot: SubingLifecyclePivot | null
  rebreak_reference_price: number | null
  retest_at: string | null
  retest_rebreak_count: number
  volume_ratio_prev: number | null
  open_interest_delta: number | null
  current_risk_codes: string[]
  risk_progress: 'watching' | null
  lower_tf_risk_count: number
  last_confirmed_stage: SubingLifecycleStage
  last_confirmed_at: string | null
  latest_transition: SubingLifecycleTransition | null
  crossed_trading_day: boolean
  boundary_reset: 'segment_changed' | null
  formal_v1_matched: boolean
}

export interface SubingResearchResponse {
  symbol: string
  product_name: string
  frequency: SubingFrequency
  actual_contract: string
  dominant_mapping_date: string
  segment_start_trading_day: string
  source_mode: 'canonical' | 'canonical_live'
  live_observation: 'available' | 'unavailable' | 'not_applicable'
  live_reason: string | null
  macd_policy_id: string
  signal_macd_policy_id: string
  calibration_state: 'accepted' | 'pending'
  calibration_id: string | null
  primary: SubingFactorResult
  companion: SubingFactorResult | null
  primary_signal: SubingSignal
  resolved_signal: SubingSignal | null
  lifecycle: SubingLifecycleSnapshot
}

export function subingLifecycleStageLabel(stage: SubingLifecycleStage): string {
  switch (stage) {
    case 'setup_armed': return '准备中'
    case 'entry_confirmed': return '研究确认'
    case 'continuation': return '延续'
    case 'exit_risk': return '退出风险'
    case 'closed': return '本轮结束'
    default: return '暂无机会'
  }
}

export function subingLifecycleProgressLabel(
  lifecycle: Pick<
    SubingLifecycleSnapshot,
    'stage' | 'entry_progress' | 'hold_count' | 'hold_required' | 'retest_rebreak_count' | 'confirmation_source'
  >,
): string {
  if (lifecycle.stage === 'setup_armed' && lifecycle.entry_progress === 'hold_confirming') {
    return `${lifecycle.hold_count}/${lifecycle.hold_required}`
  }
  if (lifecycle.stage === 'setup_armed' && lifecycle.entry_progress === 'retest_confirming') {
    return `${lifecycle.retest_rebreak_count}/${lifecycle.hold_required}`
  }
  if (
    lifecycle.stage === 'entry_confirmed'
    || lifecycle.stage === 'continuation'
    || lifecycle.stage === 'exit_risk'
    || (lifecycle.stage === 'closed' && lifecycle.confirmation_source !== null)
  ) return '已研究确认'
  return '—'
}

export function subingSignalLabel(
  signal: Pick<SubingSignal, 'status' | 'direction'>,
): string {
  if (signal.status === 'matched' && signal.direction === 'long') return '买入信号'
  if (signal.status === 'matched' && signal.direction === 'short') return '卖出信号'
  if (signal.status === 'research_pending') return '研究参数/能力待冻结'
  if (signal.status === 'insufficient_data') return '指标 warm-up 中 / 数据不足'
  return '当前不匹配'
}

/** FastAPI serializes Decimal fields as strings; normalize the complete Factor snapshot. */
export function normalizeSubingResearch(payload: SubingResearchResponse): SubingResearchResponse {
  return {
    ...payload,
    primary: normalizeSubingFactorResult(payload.primary),
    companion: payload.companion ? normalizeSubingFactorResult(payload.companion) : null,
    lifecycle: normalizeSubingLifecycle(payload.lifecycle),
  }
}

function normalizeSubingLifecycle(snapshot: SubingLifecycleSnapshot): SubingLifecycleSnapshot {
  return {
    ...snapshot,
    bound_reference_pivot: snapshot.bound_reference_pivot
      ? { ...snapshot.bound_reference_pivot, price: Number(snapshot.bound_reference_pivot.price) }
      : null,
    rebreak_reference_price: snapshot.rebreak_reference_price === null ? null : Number(snapshot.rebreak_reference_price),
    volume_ratio_prev: snapshot.volume_ratio_prev === null ? null : Number(snapshot.volume_ratio_prev),
    open_interest_delta: snapshot.open_interest_delta === null ? null : Number(snapshot.open_interest_delta),
  }
}

function normalizeSubingFactorResult(result: SubingFactorResult): SubingFactorResult {
  if (!result.snapshot) return { ...result, snapshot: null }
  const snapshot = result.snapshot
  return {
    ...result,
    snapshot: {
      ...snapshot,
      close: Number(snapshot.close),
      ema21: Number(snapshot.ema21),
      slope_5_raw: Number(snapshot.slope_5_raw),
      slope_10_raw: Number(snapshot.slope_10_raw),
      slope_5_bps_per_bar: Number(snapshot.slope_5_bps_per_bar),
      slope_10_bps_per_bar: Number(snapshot.slope_10_bps_per_bar),
      macd_dif: Number(snapshot.macd_dif),
      macd_dea: Number(snapshot.macd_dea),
      macd_histogram: Number(snapshot.macd_histogram),
      macd_cross_level: Number(snapshot.macd_cross_level),
      macd_zero_distance_abs: Number(snapshot.macd_zero_distance_abs),
      macd_zero_distance_bps: Number(snapshot.macd_zero_distance_bps),
      volume: Number(snapshot.volume),
      previous_volume: Number(snapshot.previous_volume),
      volume_ratio_prev: snapshot.volume_ratio_prev === null
        ? null
        : Number(snapshot.volume_ratio_prev),
    },
  }
}

/** Keep chart-derived EMA/MACD state local to the current rank1 segment. */
export function filterBarsToSubingSegment(bars: BarData[], segmentStart: string): BarData[] {
  return bars.filter((bar) => (bar.trading_day || '') >= segmentStart)
}

export function isSubingSupportedFrequency(frequency: MarketFrequency): frequency is SubingFrequency {
  return SUBING_PUBLIC_FREQUENCIES.includes(frequency as SubingFrequency)
}

export function shouldScheduleSubingCompanionRefresh(payload: SubingResearchResponse): boolean {
  const primary = payload.primary.snapshot
  const companion = payload.companion?.snapshot
  if (payload.frequency !== '5m' || !primary || !companion) return false
  const primaryEnd = Date.parse(primary.bar_end)
  const companionEnd = Date.parse(companion.bar_end)
  if (!Number.isFinite(primaryEnd) || !Number.isFinite(companionEnd)) return false
  return new Date(primaryEnd).getUTCMinutes() % 15 === 0 && companionEnd < primaryEnd
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
}

export interface MarketRadarResponse {
  status: 'ready' | 'degraded'
  expected_as_of: string
  target_as_of: string
  data_as_of: string
  freshness_state: 'current' | 'pending_after_market' | 'degraded'
  freshness_message: '当前完整' | '盘后更新待完成' | '数据异常'
  active_count: number
  participant_count: number
  stale: string[]
  unavailable: string[]
  summary: MarketRadarSummary
  items: MarketRadarItem[]
  sector_summary: MarketRadarSectorSummary[]
}

/** FastAPI serializes Radar Decimal values as strings; normalize at the HTTP boundary. */
export function normalizeMarketRadar(payload: MarketRadarResponse): MarketRadarResponse {
  return {
    ...payload,
    items: payload.items.map((item) => ({
      ...item,
      price_change_1d: normalizeMarketRadarDecimal(item.price_change_1d),
      price_change_5d: normalizeMarketRadarDecimal(item.price_change_5d),
      volume_ratio20: normalizeMarketRadarDecimal(item.volume_ratio20),
      oi_change_1d: normalizeMarketRadarDecimal(item.oi_change_1d),
      atr14_percentile252: normalizeMarketRadarDecimal(item.atr14_percentile252),
      position20: normalizeMarketRadarDecimal(item.position20),
      turnover: normalizeMarketRadarDecimal(item.turnover),
    })),
    sector_summary: payload.sector_summary.map((sector) => ({
      ...sector,
      median_price_change_1d: normalizeMarketRadarDecimal(sector.median_price_change_1d),
    })),
  }
}

function normalizeMarketRadarDecimal(value: number | string | null): number | null {
  return value === null ? null : Number(value)
}

export type SubingDailyWatchDecision = 'long_watch' | 'short_watch'
export type SubingDailyWatchPriceSide = 'above' | 'below' | 'equal' | 'unavailable'

interface SubingDailyWatchTrendBase<TDecimal> {
  bar_end: string
  trading_day: string
  physical_contract: string
  segment_start_trading_day: string
  close: TDecimal
  ema21: TDecimal
  price_side: SubingDailyWatchPriceSide
  slope_5_bps_per_bar: TDecimal
  slope_10_bps_per_bar: TDecimal
}

export type SubingDailyWatchTrendWire = SubingDailyWatchTrendBase<string>
export type SubingDailyWatchTrend = SubingDailyWatchTrendBase<number>

interface SubingDailyWatchItemBase<TTrend> {
  symbol: string
  product_name: string
  sector: string
  decision: SubingDailyWatchDecision | 'unavailable'
  reason_codes: string[]
  daily: TTrend | null
  hourly: TTrend | null
  unavailable_reasons: string[]
}

export type SubingDailyWatchItemWire = SubingDailyWatchItemBase<SubingDailyWatchTrendWire>
export type SubingDailyWatchItem = SubingDailyWatchItemBase<SubingDailyWatchTrend>

export interface SubingDailyWatchCounts {
  universe: number
  long_watch: number
  short_watch: number
  excluded: number
  unavailable: number
}

interface SubingDailyWatchSnapshotBase<TItem> {
  source_trading_day: string
  target_trading_day: string
  generated_at: string
  counts: SubingDailyWatchCounts
  long_watch: TItem[]
  short_watch: TItem[]
  unavailable: TItem[]
}

export type SubingDailyWatchSnapshotWire = SubingDailyWatchSnapshotBase<SubingDailyWatchItemWire>
export type SubingDailyWatchSnapshot = SubingDailyWatchSnapshotBase<SubingDailyWatchItem>

interface SubingDailyWatchCurrentResponseBase<TSnapshot> {
  status: 'ready' | 'unavailable'
  expected_target_trading_day: string | null
  latest_target_trading_day: string | null
  error_code: string | null
  snapshot: TSnapshot | null
}

export type SubingDailyWatchCurrentWireResponse =
  SubingDailyWatchCurrentResponseBase<SubingDailyWatchSnapshotWire>
export type SubingDailyWatchCurrentResponse =
  SubingDailyWatchCurrentResponseBase<SubingDailyWatchSnapshot>

export function normalizeSubingDailyWatchCurrent(
  payload: SubingDailyWatchCurrentWireResponse,
): SubingDailyWatchCurrentResponse {
  if (!isSubingDailyWatchRecord(payload)
    || (payload.status !== 'ready' && payload.status !== 'unavailable')
    || !isNullableDailyWatchDate(payload.expected_target_trading_day)
    || !isNullableDailyWatchDate(payload.latest_target_trading_day)
    || (payload.error_code !== null && !isNonEmptyDailyWatchString(payload.error_code))) {
    throw new Error('SUBING_DAILY_WATCH_INVALID_RESPONSE')
  }
  if (payload.status === 'unavailable') {
    if (payload.snapshot !== null || payload.error_code === null) {
      throw new Error('SUBING_DAILY_WATCH_INVALID_RESPONSE')
    }
    return {
      status: payload.status,
      expected_target_trading_day: payload.expected_target_trading_day,
      latest_target_trading_day: payload.latest_target_trading_day,
      error_code: payload.error_code,
      snapshot: null,
    }
  }
  if (payload.error_code !== null || !isSubingDailyWatchSnapshotWire(payload.snapshot)) {
    throw new Error('SUBING_DAILY_WATCH_INVALID_RESPONSE')
  }
  const snapshot = payload.snapshot
  if (payload.expected_target_trading_day !== snapshot.target_trading_day
    || payload.latest_target_trading_day !== snapshot.target_trading_day) {
    throw new Error('SUBING_DAILY_WATCH_INVALID_RESPONSE')
  }
  const longWatch = snapshot.long_watch.map((item) => normalizeSubingDailyWatchItem(item, 'long_watch'))
  const shortWatch = snapshot.short_watch.map((item) => normalizeSubingDailyWatchItem(item, 'short_watch'))
  const unavailable = snapshot.unavailable.map((item) => normalizeSubingDailyWatchItem(item, 'unavailable'))
  const symbols = [...longWatch, ...shortWatch, ...unavailable].map((item) => item.symbol)
  if (new Set(symbols).size !== symbols.length
    || snapshot.counts.long_watch !== longWatch.length
    || snapshot.counts.short_watch !== shortWatch.length
    || snapshot.counts.unavailable !== unavailable.length
    || snapshot.counts.universe !== (
      snapshot.counts.long_watch
      + snapshot.counts.short_watch
      + snapshot.counts.excluded
      + snapshot.counts.unavailable
    )) {
    throw new Error('SUBING_DAILY_WATCH_INVALID_RESPONSE')
  }
  return {
    status: 'ready',
    expected_target_trading_day: payload.expected_target_trading_day,
    latest_target_trading_day: payload.latest_target_trading_day,
    error_code: null,
    snapshot: {
      source_trading_day: snapshot.source_trading_day,
      target_trading_day: snapshot.target_trading_day,
      generated_at: snapshot.generated_at,
      counts: { ...snapshot.counts },
      long_watch: longWatch,
      short_watch: shortWatch,
      unavailable,
    },
  }
}

function normalizeSubingDailyWatchItem(
  value: SubingDailyWatchItemWire,
  expectedDecision: SubingDailyWatchDecision | 'unavailable',
): SubingDailyWatchItem {
  if (!isSubingDailyWatchItemWire(value) || value.decision !== expectedDecision) {
    throw new Error('SUBING_DAILY_WATCH_INVALID_RESPONSE')
  }
  if (expectedDecision !== 'unavailable' && (value.daily === null || value.hourly === null)) {
    throw new Error('SUBING_DAILY_WATCH_INVALID_RESPONSE')
  }
  if (expectedDecision === 'unavailable' && value.unavailable_reasons.length === 0) {
    throw new Error('SUBING_DAILY_WATCH_INVALID_RESPONSE')
  }
  return {
    symbol: value.symbol,
    product_name: value.product_name,
    sector: value.sector,
    decision: value.decision,
    reason_codes: [...value.reason_codes],
    daily: value.daily ? normalizeSubingDailyWatchTrend(value.daily) : null,
    hourly: value.hourly ? normalizeSubingDailyWatchTrend(value.hourly) : null,
    unavailable_reasons: [...value.unavailable_reasons],
  }
}

function normalizeSubingDailyWatchTrend(
  value: SubingDailyWatchTrendWire,
): SubingDailyWatchTrend {
  return {
    bar_end: value.bar_end,
    trading_day: value.trading_day,
    physical_contract: value.physical_contract,
    segment_start_trading_day: value.segment_start_trading_day,
    close: normalizeSubingDailyWatchDecimal(value.close),
    ema21: normalizeSubingDailyWatchDecimal(value.ema21),
    price_side: value.price_side,
    slope_5_bps_per_bar: normalizeSubingDailyWatchDecimal(value.slope_5_bps_per_bar),
    slope_10_bps_per_bar: normalizeSubingDailyWatchDecimal(value.slope_10_bps_per_bar),
  }
}

function normalizeSubingDailyWatchDecimal(value: string): number {
  if (typeof value !== 'string'
    || !/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$/.test(value)) {
    throw new Error('SUBING_DAILY_WATCH_INVALID_RESPONSE')
  }
  const normalized = Number(value)
  if (!Number.isFinite(normalized)) {
    throw new Error('SUBING_DAILY_WATCH_INVALID_RESPONSE')
  }
  return Object.is(normalized, -0) ? 0 : normalized
}

function isSubingDailyWatchSnapshotWire(value: unknown): value is SubingDailyWatchSnapshotWire {
  if (!isSubingDailyWatchRecord(value)
    || !isDailyWatchDate(value.source_trading_day)
    || !isDailyWatchDate(value.target_trading_day)
    || !isDailyWatchTimestamp(value.generated_at)
    || !isSubingDailyWatchCounts(value.counts)
    || !Array.isArray(value.long_watch)
    || !Array.isArray(value.short_watch)
    || !Array.isArray(value.unavailable)) return false
  return true
}

function isSubingDailyWatchCounts(value: unknown): value is SubingDailyWatchCounts {
  if (!isSubingDailyWatchRecord(value)) return false
  return ['universe', 'long_watch', 'short_watch', 'excluded', 'unavailable']
    .every((key) => Number.isInteger(value[key]) && Number(value[key]) >= 0)
}

function isSubingDailyWatchItemWire(value: unknown): value is SubingDailyWatchItemWire {
  if (!isSubingDailyWatchRecord(value)
    || !isDailyWatchSymbol(value.symbol)
    || typeof value.product_name !== 'string'
    || typeof value.sector !== 'string'
    || !['long_watch', 'short_watch', 'unavailable'].includes(String(value.decision))
    || !isDailyWatchStringArray(value.reason_codes)
    || !isDailyWatchStringArray(value.unavailable_reasons)) return false
  return (value.daily === null || isSubingDailyWatchTrendWire(value.daily))
    && (value.hourly === null || isSubingDailyWatchTrendWire(value.hourly))
}

function isSubingDailyWatchTrendWire(value: unknown): value is SubingDailyWatchTrendWire {
  if (!isSubingDailyWatchRecord(value)) return false
  return isDailyWatchTimestamp(value.bar_end)
    && isDailyWatchDate(value.trading_day)
    && isNonEmptyDailyWatchString(value.physical_contract)
    && isDailyWatchDate(value.segment_start_trading_day)
    && typeof value.close === 'string'
    && typeof value.ema21 === 'string'
    && ['above', 'below', 'equal', 'unavailable'].includes(String(value.price_side))
    && typeof value.slope_5_bps_per_bar === 'string'
    && typeof value.slope_10_bps_per_bar === 'string'
}

function isSubingDailyWatchRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function isDailyWatchStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every(isNonEmptyDailyWatchString)
}

function isDailyWatchSymbol(value: unknown): value is string {
  return typeof value === 'string' && /^[a-z]+$/.test(value)
}

function isNonEmptyDailyWatchString(value: unknown): value is string {
  return typeof value === 'string' && value.length > 0
}

function isDailyWatchDate(value: unknown): value is string {
  return typeof value === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(value)
}

function isNullableDailyWatchDate(value: unknown): value is string | null {
  return value === null || isDailyWatchDate(value)
}

function isDailyWatchTimestamp(value: unknown): value is string {
  return typeof value === 'string' && value.length > 0 && Number.isFinite(Date.parse(value))
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

export type MarketOverlaySource = 'none' | 'realtime' | 'post_close'

export type MarketWsMessage =
  | { type: 'state'; state: MarketReadState }
  | {
      type: 'snapshot'
      source: MarketOverlaySource
      trading_day: string | null
      contract: string | null
      bars: CanonicalBarDto[]
    }
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

export interface SubingHistoricalSignalRequest {
  series_kind: 'actual_dominant'
  symbol: string
  frequency: '5m' | '15m'
  since: string
  through: string
}

export interface SubingHistoricalSignalEvent {
  event_id: string
  bar_end: string
  trading_day: string
  contract: string
  segment_start_trading_day: string
  direction: 'buy' | 'sell'
  trigger_timeframe: '5m' | '15m'
  lower_tf_confirmation: boolean
}

export interface SubingHistoricalSignalResponse {
  request: SubingHistoricalSignalRequest
  events: SubingHistoricalSignalEvent[]
}

export interface JdjStrategyHistoricalRequest {
  series_kind: 'actual_dominant'
  symbol: string
  frequency: '1m'
  since: string
  through: string
}

export type JdjStrategyActionKind =
  | 'entry'
  | 'add'
  | 'reduce'
  | 'exit'
  | 'rejected'
  | 'daily_pause'
  | 'daily_stop'

export interface JdjStrategyHistoricalAction {
  event_id: string
  episode_id: string | null
  kind: JdjStrategyActionKind
  source_event_ids: string[]
  primary_setup: string | null
  supporting_setups: string[]
  direction: 'long' | 'short' | null
  contract: string
  trading_day: string
  segment_start_trading_day: string
  decision_at: string
  effective_bar_end: string | null
  reference_price: string | null
  quantity: number
  position_quantity_after: number
  stop_price: string | null
  target_price: string | null
  reward_risk: string | null
  reason: string
  fill_basis: string | null
}

export interface JdjStrategyHistoricalResponse {
  request: JdjStrategyHistoricalRequest
  reference_execution: boolean
  actions: JdjStrategyHistoricalAction[]
}

export interface NStructureBandRequest {
  series_kind: 'actual_dominant'
  symbol: string
  frequency: '5m'
  since: string
  through: string
}

export interface NStructureBandPolicy {
  policy_id: 'n_structure_5m_v1'
  formula_version: 'n_structure_v1'
  source_timeframe: '5m'
  research_only: true
}

export interface NStructureBand {
  band_id: string
  contract: string
  segment_start_trading_day: string
  completion_trading_day: string
  direction: 'up' | 'down'
  role: 'support_reference' | 'resistance_reference'
  n1_at: string
  completed_at: string
  completion_level: number
  lower: number
  upper: number
  first_reentered_at: string | null
  invalidated_at: string | null
  expanded_until: string
}

export interface NStructureBandWire extends Omit<
  NStructureBand,
  'completion_level' | 'lower' | 'upper'
> {
  completion_level: number | string
  lower: number | string
  upper: number | string
}

export interface NStructureBandResponse {
  request: NStructureBandRequest
  policy: NStructureBandPolicy
  bands: NStructureBand[]
}

export interface NStructureBandWireResponse extends Omit<NStructureBandResponse, 'bands'> {
  bands: NStructureBandWire[]
}

/** Alert V2 `AlertEventOut`：只读展示 DTO，方向语义见 result_codes。 */
export interface AlertEvent {
  id: number
  rule_code: string
  symbol: string
  contract: string
  trading_day: string | null
  frequency: MarketFrequency
  bar_end: string
  result_codes: Array<'buy' | 'sell'>
  lower_tf_confirmation: boolean
  detected_at: string
  notification_attempted_at: string | null
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
export type MainIndicatorId = 'ema_10' | 'ema_20' | 'ema_21' | 'ema_60' | 'htdy'
export type OptionalEmaIndicatorId = 'ema_10' | 'ema_60'

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
  macd?: { dif?: number | null; dea?: number | null; histogram?: number | null } | null
  atr?: number | null
  marker?: KlineMarker | null
  cursorPrice?: number | null
}
