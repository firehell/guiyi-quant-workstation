export const MARKET_FREQUENCIES = ['1m', '5m', '15m', '30m', '60m', '1d', '1w'] as const
export type MarketFrequency = (typeof MARKET_FREQUENCIES)[number]
export type SeriesKind = 'continuous' | 'actual_dominant' | 'contract'
export type ResearchOverlayId = 'none' | 'subing' | 'htdy'

export interface ResearchOverlayDefinition {
  id: ResearchOverlayId
  label: string
  supportedSeriesKinds: readonly SeriesKind[]
  supportedFrequencies: readonly MarketFrequency[]
  mainIndicators: readonly MainIndicatorId[]
  historicalSource: 'none' | 'local' | 'subing_strategy'
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
  trigger_reference_pivot: SubingLifecyclePivot | null
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
    trigger_reference_pivot: snapshot.trigger_reference_pivot
      ? { ...snapshot.trigger_reference_pivot, price: Number(snapshot.trigger_reference_pivot.price) }
      : null,
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
export type SubingDailyWatchProjectionVersion = 'subing_daily_watch_v2'
export type SubingDailyWatchFormulaVersion = 'subing_ema21_rank1_stitched_raw_v2'
export type SubingDailyWatchHistoryMode = 'rank1_stitched_raw'

interface SubingDailyWatchTrendBase<TDecimal> {
  bar_end: string
  trading_day: string
  physical_contract: string
  current_segment_start_trading_day: string
  warmup_start_trading_day: string
  warmup_bar_count: number
  warmup_segment_count: number
  history_mode: SubingDailyWatchHistoryMode
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
  projection_version: SubingDailyWatchProjectionVersion
  formula_version: SubingDailyWatchFormulaVersion
  history_mode: SubingDailyWatchHistoryMode
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
    || payload.projection_version !== 'subing_daily_watch_v2'
    || payload.formula_version !== 'subing_ema21_rank1_stitched_raw_v2'
    || payload.history_mode !== 'rank1_stitched_raw'
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
      projection_version: payload.projection_version,
      formula_version: payload.formula_version,
      history_mode: payload.history_mode,
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
    projection_version: payload.projection_version,
    formula_version: payload.formula_version,
    history_mode: payload.history_mode,
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
    current_segment_start_trading_day: value.current_segment_start_trading_day,
    warmup_start_trading_day: value.warmup_start_trading_day,
    warmup_bar_count: value.warmup_bar_count,
    warmup_segment_count: value.warmup_segment_count,
    history_mode: value.history_mode,
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
    && isDailyWatchDate(value.current_segment_start_trading_day)
    && isDailyWatchDate(value.warmup_start_trading_day)
    && value.warmup_bar_count === 30
    && Number.isInteger(value.warmup_segment_count)
    && Number(value.warmup_segment_count) >= 1
    && Number(value.warmup_segment_count) <= 30
    && value.history_mode === 'rank1_stitched_raw'
    && value.current_segment_start_trading_day <= value.trading_day
    && value.warmup_start_trading_day <= value.trading_day
    && !Object.hasOwn(value, 'segment_start_trading_day')
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
  if (typeof value !== 'string') return false
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value)
  if (match === null) return false
  const year = Number(match[1])
  const month = Number(match[2])
  const day = Number(match[3])
  if (year < 1 || year > 9999 || month < 1 || month > 12 || day < 1) return false
  const daysInMonth = [31, isDailyWatchLeapYear(year) ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
  return day <= daysInMonth[month - 1]
}

function isDailyWatchLeapYear(year: number): boolean {
  return year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0)
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
  /** SuBing close-label PnL color; independent of direction tone. */
  resultTone?: 'profit' | 'loss' | null
  position: 'aboveBar' | 'belowBar' | 'inBar'
  shape: 'circle' | 'square' | 'arrowUp' | 'arrowDown'
}

export interface SubingStrategyHistoricalRequest {
  series_kind: 'actual_dominant'
  symbol: string
  frequency: '15m'
  since: string
  through: string
}

export type SubingStrategyActionKind =
  | 'open_long' | 'open_short' | 'close_long' | 'close_short'
export type SubingStrategyFillBasis = 'next_bar_open' | 'segment_terminal_close'
export type SubingStrategyConfirmationSource =
  | 'formal_v1' | 'momentum_hold' | 'pivot_break_hold' | 'pivot_retest_rebreak'
export type SubingStrategyLongExitReason =
  | 'EMA21_BREACH_LONG'
  | 'PREVIOUS_BAR_LOW_BREACH'
  | 'BOUND_LOW_PIVOT_BREACH'
  | 'MACD_HIGH_DEAD_CROSS'
  | 'CONTRACT_SEGMENT_END'
export type SubingStrategyShortExitReason =
  | 'EMA21_BREACH_SHORT'
  | 'PREVIOUS_BAR_HIGH_BREACH'
  | 'BOUND_HIGH_PIVOT_BREACH'
  | 'MACD_LOW_GOLDEN_CROSS'
  | 'CONTRACT_SEGMENT_END'

export interface SubingStrategyBoundPivotWire {
  pivot_id: string
  kind: 'high' | 'low'
  source_timeframe: '5m'
  pivot_time: string
  confirmed_at: string
  price: string
  contract: string
  segment_start_trading_day: string
}

export type SubingStrategyBoundPivot = SubingStrategyBoundPivotWire

export interface SubingStrategyBoundLowPivotWire extends Omit<SubingStrategyBoundPivotWire, 'kind'> {
  kind: 'low'
}

export interface SubingStrategyBoundHighPivotWire extends Omit<SubingStrategyBoundPivotWire, 'kind'> {
  kind: 'high'
}

export interface SubingStrategyActionWire {
  action_id: string
  episode_id: string
  strategy_id: 'subing_strategy_v1'
  formula_version: 'subing_strategy_15m_v1'
  kind: SubingStrategyActionKind
  symbol: string
  contract: string
  trading_day: string
  segment_start_trading_day: string
  opportunity_id: string
  decision_at: string
  effective_open_at: string | null
  effective_bar_end: string
  reference_price: string
  fill_basis: SubingStrategyFillBasis
  confirmation_source: SubingStrategyConfirmationSource | null
  reason_codes: string[]
  direction_context_source_day: string | null
  direction_context_target_day: string | null
  bound_reference_pivot: SubingStrategyBoundPivotWire | null
}

export interface SubingStrategyAction extends Omit<
  SubingStrategyActionWire,
  'bound_reference_pivot'
> {
  bound_reference_pivot: SubingStrategyBoundPivot | null
}

interface SubingStrategyEventEntryCommonWire {
  action_id: string
  effective_bar_end: string
  reference_price: string
  confirmation_source: SubingStrategyConfirmationSource
}

export interface SubingStrategyOpenLongEntryWire extends SubingStrategyEventEntryCommonWire {
  kind: 'open_long'
}

export interface SubingStrategyOpenShortEntryWire extends SubingStrategyEventEntryCommonWire {
  kind: 'open_short'
}

type SubingStrategyActionPayloadCommonWire = Omit<
  SubingStrategyActionWire,
  | 'kind' | 'effective_open_at' | 'fill_basis' | 'confirmation_source'
  | 'reason_codes' | 'direction_context_source_day'
  | 'direction_context_target_day' | 'bound_reference_pivot'
> & {
  schema_version: 1
}

export type SubingStrategyOpenLongActionPayloadWire = SubingStrategyActionPayloadCommonWire & {
  kind: 'open_long'
  effective_open_at: string
  fill_basis: 'next_bar_open'
  confirmation_source: SubingStrategyConfirmationSource
  reason_codes: []
  direction_context_source_day: string
  direction_context_target_day: string
  bound_reference_pivot: SubingStrategyBoundLowPivotWire | null
  entry: null
  holding_bar_count: null
  reference_change_percent: null
}

export type SubingStrategyOpenShortActionPayloadWire = SubingStrategyActionPayloadCommonWire & {
  kind: 'open_short'
  effective_open_at: string
  fill_basis: 'next_bar_open'
  confirmation_source: SubingStrategyConfirmationSource
  reason_codes: []
  direction_context_source_day: string
  direction_context_target_day: string
  bound_reference_pivot: SubingStrategyBoundHighPivotWire | null
  entry: null
  holding_bar_count: null
  reference_change_percent: null
}

type SubingStrategyNextOpenFillWire = {
  fill_basis: 'next_bar_open'
  effective_open_at: string
}

type SubingStrategyTerminalFillWire = {
  fill_basis: 'segment_terminal_close'
  effective_open_at: null
}

export type SubingStrategyCloseLongActionPayloadWire = SubingStrategyActionPayloadCommonWire & {
  kind: 'close_long'
  confirmation_source: null
  reason_codes: [SubingStrategyLongExitReason, ...SubingStrategyLongExitReason[]]
  direction_context_source_day: null
  direction_context_target_day: null
  bound_reference_pivot: SubingStrategyBoundLowPivotWire | null
  entry: SubingStrategyOpenLongEntryWire
  holding_bar_count: number
  reference_change_percent: string
} & (SubingStrategyNextOpenFillWire | SubingStrategyTerminalFillWire)

export type SubingStrategyCloseShortActionPayloadWire = SubingStrategyActionPayloadCommonWire & {
  kind: 'close_short'
  confirmation_source: null
  reason_codes: [SubingStrategyShortExitReason, ...SubingStrategyShortExitReason[]]
  direction_context_source_day: null
  direction_context_target_day: null
  bound_reference_pivot: SubingStrategyBoundHighPivotWire | null
  entry: SubingStrategyOpenShortEntryWire
  holding_bar_count: number
  reference_change_percent: string
} & (SubingStrategyNextOpenFillWire | SubingStrategyTerminalFillWire)

export type SubingStrategyActionPayloadWire =
  | SubingStrategyOpenLongActionPayloadWire
  | SubingStrategyOpenShortActionPayloadWire
  | SubingStrategyCloseLongActionPayloadWire
  | SubingStrategyCloseShortActionPayloadWire

export interface SubingStrategyEpisodeWire {
  episode_id: string
  direction: 'long' | 'short'
  entry_action: SubingStrategyActionWire
  exit_action: SubingStrategyActionWire | null
  state: 'open' | 'closed'
  holding_bar_count: number
  reference_change_percent: string | null
  current_reference_change_percent: string | null
  latest_reference_price: string | null
  exit_reason_codes: string[]
  structure_exit_available: boolean
}

export interface SubingStrategyEpisode extends Omit<
  SubingStrategyEpisodeWire,
  'entry_action' | 'exit_action'
> {
  entry_action: SubingStrategyAction
  exit_action: SubingStrategyAction | null
}

export interface SubingStrategyHistoricalWireResponse {
  request: SubingStrategyHistoricalRequest
  policy: {
    strategy_id: 'subing_strategy_v1'
    formula_version: 'subing_strategy_15m_v1'
    research_only: true
    series_kind: 'actual_dominant'
    decision_frequency: '15m'
    lifecycle_policy_id: 'subing_lifecycle_v2_research_v1'
    allowed_confirmation_sources: SubingStrategyConfirmationSource[]
  }
  resolved_cutoff: string
  segment_summaries: Array<{
    contract: string
    start_trading_day: string
    end_trading_day: string
    loaded_through: string
    bar_count_5m: number
    bar_count_15m: number
    initial_position: 'flat'
    final_position: 'flat' | 'long' | 'short'
    terminal_bar_end: string | null
    pending_action: boolean
  }>
  actions: SubingStrategyActionWire[]
  episodes: SubingStrategyEpisodeWire[]
  context_unavailable: Array<{
    symbol: string
    target_trading_day: string
    source_trading_day: string | null
    direction: 'unavailable'
    reason_codes: string[]
    daily_bar_end: string | null
    hourly_bar_end: string | null
    physical_contract: string | null
  }>
  cache_state: 'hit' | 'miss' | 'mixed' | 'unavailable'
}

export interface SubingStrategyHistoricalResponse extends Omit<
  SubingStrategyHistoricalWireResponse,
  'actions' | 'episodes'
> {
  actions: SubingStrategyAction[]
  episodes: SubingStrategyEpisode[]
}

export interface SubingStrategyPerformanceStats {
  completed: number
  positive: number
  negative: number
  flat: number
  positive_rate_percent: string | null
  mean_reference_change_percent: string | null
  median_reference_change_percent: string | null
  best_reference_change_percent: string | null
  worst_reference_change_percent: string | null
  mean_holding_15m_bars: string | null
}

export interface SubingStrategyPerformanceResponse {
  strategy_id: SubingStrategyHistoricalWireResponse['policy']['strategy_id']
  formula_version: 'subing_strategy_15m_v1'
  symbol: string
  series_kind: 'actual_dominant'
  frequency: '15m'
  coverage: {
    since: string
    through: string
    resolved_cutoff: string
    segment_count: number
    bar_count_15m: number
    context_unavailable_count: number
  }
  cache_state: 'hit' | 'refreshed' | 'unavailable'
  cache_identity_sha256: string | null
  cache_generated_at: string | null
  summary: {
    overall: SubingStrategyPerformanceStats
    long: SubingStrategyPerformanceStats
    short: SubingStrategyPerformanceStats
    open_episodes: number
  }
  exit_reason_counts: Array<{ reason_code: string; count: number }>
  episodes: SubingStrategyEpisode[]
}

export interface SubingStrategyPendingSummary {
  kind: SubingStrategyActionKind
  decision_at: string
  opportunity_id: string
  reason_codes: string[]
}

export interface SubingStrategyCurrentContext {
  symbol: string
  target_trading_day: string
  source_trading_day: string | null
  direction: 'long_only' | 'short_only' | 'no_new_entry' | 'unavailable'
  reason_codes: string[]
  daily_bar_end: string | null
  hourly_bar_end: string | null
  physical_contract: string | null
}

export interface SubingStrategyCurrentWireResponse {
  strategy_id: SubingStrategyHistoricalWireResponse['policy']['strategy_id']
  formula_version: 'subing_strategy_15m_v1'
  series_kind: 'actual_dominant'
  symbol: string
  frequency: '15m'
  contract: string
  segment_start_trading_day: string
  source_mode: 'canonical' | 'canonical_live'
  cutoff: string
  position_state: 'flat' | 'long' | 'short'
  pending_action: SubingStrategyPendingSummary | null
  current_episode: SubingStrategyEpisodeWire | null
  latest_completed_episode: SubingStrategyEpisodeWire | null
  direction_context: SubingStrategyCurrentContext
}

export interface SubingStrategyCurrentResponse extends Omit<
  SubingStrategyCurrentWireResponse,
  'current_episode' | 'latest_completed_episode'
> {
  current_episode: SubingStrategyEpisode | null
  latest_completed_episode: SubingStrategyEpisode | null
}

const SUBING_STRATEGY_CONFIRMATION_SOURCES = [
  'formal_v1', 'momentum_hold', 'pivot_break_hold', 'pivot_retest_rebreak',
] as const
const SUBING_STRATEGY_ACTION_KINDS = [
  'open_long', 'open_short', 'close_long', 'close_short',
] as const
const SUBING_STRATEGY_SEGMENT_CACHE_STATES = ['hit', 'miss', 'mixed', 'unavailable'] as const
const SUBING_STRATEGY_PERFORMANCE_CACHE_STATES = ['hit', 'refreshed', 'unavailable'] as const

function invalidSubingStrategyResponse(): never {
  throw new Error('SUBING_STRATEGY_INVALID_RESPONSE')
}

function strategyRecord(value: unknown): Record<string, unknown> {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) {
    invalidSubingStrategyResponse()
  }
  return value as Record<string, unknown>
}

function strategyString(value: unknown): string {
  if (typeof value !== 'string' || value.length === 0) invalidSubingStrategyResponse()
  return value
}

function strategyDate(value: unknown): string {
  const result = strategyString(value)
  if (!/^\d{4}-\d{2}-\d{2}$/.test(result)) invalidSubingStrategyResponse()
  return result
}

function strategyTimestamp(value: unknown): string {
  const result = strategyString(value)
  if (!Number.isFinite(Date.parse(result))) invalidSubingStrategyResponse()
  return result
}

function strategyNullableTimestamp(value: unknown): string | null {
  return value === null ? null : strategyTimestamp(value)
}

function strategyDecimal(value: unknown): string {
  if (typeof value !== 'string' || value === '' || value !== value.trim()) {
    invalidSubingStrategyResponse()
  }
  const match = /^([+-]?)(\d+)(?:\.(\d*))?(?:[eE]([+-]?\d+))?$/.exec(value)
  if (!match) invalidSubingStrategyResponse()
  const exponent = Number(match[4] ?? '0')
  if (!Number.isSafeInteger(exponent)) invalidSubingStrategyResponse()
  const fraction = match[3] ?? ''
  const digits = `${match[2]}${fraction}`
  const decimalIndex = match[2].length + exponent
  if (digits.length + Math.abs(exponent) > 10_000) invalidSubingStrategyResponse()
  const expanded = decimalIndex <= 0
    ? `0.${'0'.repeat(-decimalIndex)}${digits}`
    : decimalIndex >= digits.length
      ? `${digits}${'0'.repeat(decimalIndex - digits.length)}`
      : `${digits.slice(0, decimalIndex)}.${digits.slice(decimalIndex)}`
  const [rawInteger, rawFraction = ''] = expanded.split('.')
  const integer = rawInteger.replace(/^0+(?=\d)/, '')
  const canonicalFraction = rawFraction.replace(/0+$/, '')
  const nonZero = integer !== '0' || canonicalFraction !== ''
  return `${match[1] === '-' && nonZero ? '-' : ''}${integer}`
    + `${canonicalFraction ? `.${canonicalFraction}` : ''}`
}

function strategyNullableDecimal(value: unknown): string | null {
  return value === null ? null : strategyDecimal(value)
}

function strategyNonnegativeInteger(value: unknown): number {
  if (!Number.isInteger(value) || Number(value) < 0) invalidSubingStrategyResponse()
  return value as number
}

function normalizeSubingStrategyPerformanceStats(
  value: unknown,
): SubingStrategyPerformanceStats {
  const stats = strategyRecord(value)
  const completed = strategyNonnegativeInteger(stats.completed)
  const positive = strategyNonnegativeInteger(stats.positive)
  const negative = strategyNonnegativeInteger(stats.negative)
  const flat = strategyNonnegativeInteger(stats.flat)
  const normalized = {
    completed,
    positive,
    negative,
    flat,
    positive_rate_percent: strategyNullableDecimal(stats.positive_rate_percent),
    mean_reference_change_percent: strategyNullableDecimal(stats.mean_reference_change_percent),
    median_reference_change_percent: strategyNullableDecimal(stats.median_reference_change_percent),
    best_reference_change_percent: strategyNullableDecimal(stats.best_reference_change_percent),
    worst_reference_change_percent: strategyNullableDecimal(stats.worst_reference_change_percent),
    mean_holding_15m_bars: strategyNullableDecimal(stats.mean_holding_15m_bars),
  }
  const aggregateValues = [
    normalized.positive_rate_percent,
    normalized.mean_reference_change_percent,
    normalized.median_reference_change_percent,
    normalized.best_reference_change_percent,
    normalized.worst_reference_change_percent,
    normalized.mean_holding_15m_bars,
  ]
  const positiveRate = normalized.positive_rate_percent === null
    ? null : Number(normalized.positive_rate_percent)
  const meanHolding = normalized.mean_holding_15m_bars === null
    ? null : Number(normalized.mean_holding_15m_bars)
  if (
    completed !== positive + negative + flat
    || (completed === 0 && aggregateValues.some((item) => item !== null))
    || (completed > 0 && aggregateValues.some((item) => item === null))
    || (positiveRate !== null && (
      !Number.isFinite(positiveRate)
      || positiveRate < 0
      || positiveRate > 100
      || Math.abs(positiveRate - positive / completed * 100) > 1e-9
    ))
    || (meanHolding !== null && (!Number.isFinite(meanHolding) || meanHolding < 0))
  ) invalidSubingStrategyResponse()
  return normalized
}

function strategyStringArray(value: unknown): string[] {
  if (!Array.isArray(value) || value.some((item) => typeof item !== 'string' || !item)) {
    invalidSubingStrategyResponse()
  }
  return [...value] as string[]
}

function strategyEnum<const T extends readonly string[]>(value: unknown, allowed: T): T[number] {
  if (typeof value !== 'string' || !allowed.includes(value)) invalidSubingStrategyResponse()
  return value as T[number]
}

function normalizeStrategyPivot(value: unknown): SubingStrategyBoundPivot | null {
  if (value === null) return null
  const pivot = strategyRecord(value)
  if (
    !['high', 'low'].includes(String(pivot.kind))
    || pivot.source_timeframe !== '5m'
  ) invalidSubingStrategyResponse()
  return {
    pivot_id: strategyString(pivot.pivot_id),
    kind: pivot.kind as 'high' | 'low',
    source_timeframe: '5m',
    pivot_time: strategyTimestamp(pivot.pivot_time),
    confirmed_at: strategyTimestamp(pivot.confirmed_at),
    price: strategyDecimal(pivot.price),
    contract: strategyString(pivot.contract),
    segment_start_trading_day: strategyDate(pivot.segment_start_trading_day),
  }
}

function normalizeStrategyAction(value: unknown): SubingStrategyAction {
  const action = strategyRecord(value)
  const kind = action.kind
  const open = kind === 'open_long' || kind === 'open_short'
  if (
    !SUBING_STRATEGY_ACTION_KINDS.includes(kind as never)
    || action.strategy_id !== 'subing_strategy_v1'
    || action.formula_version !== 'subing_strategy_15m_v1'
    || !['next_bar_open', 'segment_terminal_close'].includes(String(action.fill_basis))
    || typeof action.symbol !== 'string'
    || action.symbol !== action.symbol.trim().toLowerCase()
    || !/^[a-z]+$/.test(action.symbol)
    || typeof action.contract !== 'string'
    || !action.contract.startsWith(action.symbol.toUpperCase())
  ) invalidSubingStrategyResponse()
  const confirmation = action.confirmation_source
  const reasons = strategyStringArray(action.reason_codes)
  if (
    !String(action.action_id).startsWith('subing-action:')
    || !String(action.episode_id).startsWith('subing-episode:')
    || !String(action.opportunity_id).startsWith('subing-opportunity:')
    || new Set(reasons).size !== reasons.length
    || (open && !SUBING_STRATEGY_CONFIRMATION_SOURCES.includes(confirmation as never))
    || (!open && confirmation !== null)
    || (open && reasons.length > 0)
    || (!open && reasons.length === 0)
  ) invalidSubingStrategyResponse()
  const decision = strategyTimestamp(action.decision_at)
  const effective = strategyTimestamp(action.effective_bar_end)
  if (
    Date.parse(effective) < Date.parse(decision)
    || (action.fill_basis === 'next_bar_open' && Date.parse(effective) <= Date.parse(decision))
    || (action.fill_basis === 'segment_terminal_close' && open)
  ) invalidSubingStrategyResponse()
  const pivot = normalizeStrategyPivot(action.bound_reference_pivot)
  if (
    pivot !== null
    && (pivot.contract !== action.contract
      || pivot.segment_start_trading_day !== action.segment_start_trading_day)
  ) invalidSubingStrategyResponse()
  return {
    action_id: strategyString(action.action_id),
    episode_id: strategyString(action.episode_id),
    strategy_id: 'subing_strategy_v1',
    formula_version: 'subing_strategy_15m_v1',
    kind: kind as SubingStrategyActionKind,
    symbol: action.symbol,
    contract: action.contract,
    trading_day: strategyDate(action.trading_day),
    segment_start_trading_day: strategyDate(action.segment_start_trading_day),
    opportunity_id: strategyString(action.opportunity_id),
    decision_at: decision,
    effective_open_at: strategyNullableTimestamp(action.effective_open_at),
    effective_bar_end: effective,
    reference_price: strategyDecimal(action.reference_price),
    fill_basis: action.fill_basis as SubingStrategyFillBasis,
    confirmation_source: confirmation as SubingStrategyConfirmationSource | null,
    reason_codes: reasons,
    direction_context_source_day: action.direction_context_source_day === null
      ? null : strategyDate(action.direction_context_source_day),
    direction_context_target_day: action.direction_context_target_day === null
      ? null : strategyDate(action.direction_context_target_day),
    bound_reference_pivot: pivot,
  }
}

function normalizeStrategyEpisode(value: unknown, expectedSymbol: string): SubingStrategyEpisode {
  const episode = strategyRecord(value)
  const entry = normalizeStrategyAction(episode.entry_action)
  const exit = episode.exit_action === null ? null : normalizeStrategyAction(episode.exit_action)
  const episodeId = strategyString(episode.episode_id)
  const direction = episode.direction
  const state = episode.state
  if (
    !['long', 'short'].includes(String(direction))
    || !['open', 'closed'].includes(String(state))
    || entry.episode_id !== episodeId
    || entry.symbol !== expectedSymbol
    || (direction === 'long' ? entry.kind !== 'open_long' : entry.kind !== 'open_short')
    || (state === 'open') !== (exit === null)
    || (exit !== null && (
      exit.episode_id !== episodeId
      || exit.symbol !== entry.symbol
      || exit.contract !== entry.contract
      || exit.opportunity_id !== entry.opportunity_id
      || (direction === 'long' ? exit.kind !== 'close_long' : exit.kind !== 'close_short')
    ))
    || !Number.isInteger(episode.holding_bar_count)
    || Number(episode.holding_bar_count) < 1
    || typeof episode.structure_exit_available !== 'boolean'
  ) invalidSubingStrategyResponse()
  const exitReasons = strategyStringArray(episode.exit_reason_codes)
  if (
    (exit !== null && exitReasons.join('|') !== exit.reason_codes.join('|'))
    || (exit === null && exitReasons.length > 0)
    || (state === 'closed' && (
      episode.reference_change_percent === null
      || episode.current_reference_change_percent !== null
      || episode.latest_reference_price !== null
    ))
    || (state === 'open' && (
      episode.reference_change_percent !== null
      || episode.current_reference_change_percent === null
      || episode.latest_reference_price === null
    ))
  ) invalidSubingStrategyResponse()
  return {
    episode_id: episodeId,
    direction: direction as 'long' | 'short',
    entry_action: entry,
    exit_action: exit,
    state: state as 'open' | 'closed',
    holding_bar_count: episode.holding_bar_count as number,
    reference_change_percent: strategyNullableDecimal(episode.reference_change_percent),
    current_reference_change_percent: strategyNullableDecimal(
      episode.current_reference_change_percent,
    ),
    latest_reference_price: strategyNullableDecimal(episode.latest_reference_price),
    exit_reason_codes: exitReasons,
    structure_exit_available: episode.structure_exit_available,
  }
}

export function normalizeSubingStrategyHistory(
  value: unknown,
): SubingStrategyHistoricalResponse {
  const payload = strategyRecord(value)
  const request = strategyRecord(payload.request)
  const policy = strategyRecord(payload.policy)
  if (
    request.series_kind !== 'actual_dominant'
    || request.frequency !== '15m'
    || policy.strategy_id !== 'subing_strategy_v1'
    || policy.formula_version !== 'subing_strategy_15m_v1'
    || policy.research_only !== true
    || policy.series_kind !== 'actual_dominant'
    || policy.decision_frequency !== '15m'
    || policy.lifecycle_policy_id !== 'subing_lifecycle_v2_research_v1'
    || !Array.isArray(policy.allowed_confirmation_sources)
    || policy.allowed_confirmation_sources.join('|')
      !== SUBING_STRATEGY_CONFIRMATION_SOURCES.join('|')
    || !SUBING_STRATEGY_SEGMENT_CACHE_STATES.includes(payload.cache_state as never)
    || !Array.isArray(payload.actions)
    || !Array.isArray(payload.episodes)
    || !Array.isArray(payload.segment_summaries)
    || !Array.isArray(payload.context_unavailable)
  ) invalidSubingStrategyResponse()
  const normalizedRequest: SubingStrategyHistoricalRequest = {
    series_kind: 'actual_dominant',
    symbol: strategyString(request.symbol),
    frequency: '15m',
    since: strategyDate(request.since),
    through: strategyDate(request.through),
  }
  if (
    normalizedRequest.symbol !== normalizedRequest.symbol.toLowerCase()
    || normalizedRequest.since > normalizedRequest.through
  ) invalidSubingStrategyResponse()
  const actions = payload.actions.map(normalizeStrategyAction)
  if (new Set(actions.map((action) => action.action_id)).size !== actions.length) {
    invalidSubingStrategyResponse()
  }
  if (actions.some((action) => (
    action.symbol !== normalizedRequest.symbol
    || action.trading_day < normalizedRequest.since
    || action.trading_day > normalizedRequest.through
  ))) invalidSubingStrategyResponse()
  const episodes = payload.episodes.map((value) => (
    normalizeStrategyEpisode(value, normalizedRequest.symbol)
  ))
  if (new Set(episodes.map((episode) => episode.episode_id)).size !== episodes.length) {
    invalidSubingStrategyResponse()
  }
  for (const value of payload.segment_summaries) {
    const summary = strategyRecord(value)
    const start = strategyDate(summary.start_trading_day)
    const end = strategyDate(summary.end_trading_day)
    const loadedThrough = strategyDate(summary.loaded_through)
    if (
      typeof summary.contract !== 'string'
      || !summary.contract.startsWith(normalizedRequest.symbol.toUpperCase())
      || start > end
      || loadedThrough < start
      || loadedThrough > end
      || !Number.isInteger(summary.bar_count_5m)
      || Number(summary.bar_count_5m) < 1
      || !Number.isInteger(summary.bar_count_15m)
      || Number(summary.bar_count_15m) < 1
      || summary.initial_position !== 'flat'
      || !['flat', 'long', 'short'].includes(String(summary.final_position))
      || typeof summary.pending_action !== 'boolean'
      || (summary.terminal_bar_end !== null
        && !Number.isFinite(Date.parse(String(summary.terminal_bar_end))))
    ) invalidSubingStrategyResponse()
  }
  for (const value of payload.context_unavailable) {
    const context = strategyRecord(value)
    if (
      context.symbol !== normalizedRequest.symbol
      || context.direction !== 'unavailable'
      || strategyDate(context.target_trading_day) < normalizedRequest.since
      || strategyDate(context.target_trading_day) > normalizedRequest.through
      || (context.source_trading_day !== null
        && !/^\d{4}-\d{2}-\d{2}$/.test(String(context.source_trading_day)))
      || strategyStringArray(context.reason_codes).length === 0
      || (context.physical_contract !== null
        && !String(context.physical_contract).startsWith(normalizedRequest.symbol.toUpperCase()))
    ) invalidSubingStrategyResponse()
  }
  strategyTimestamp(payload.resolved_cutoff)
  return {
    ...(payload as unknown as SubingStrategyHistoricalWireResponse),
    request: normalizedRequest,
    actions,
    episodes,
  }
}

export function normalizeSubingStrategyPerformance(
  value: unknown,
): SubingStrategyPerformanceResponse {
  const payload = strategyRecord(value)
  const coverage = strategyRecord(payload.coverage)
  const summary = strategyRecord(payload.summary)
  if (
    payload.strategy_id !== 'subing_strategy_v1'
    || payload.formula_version !== 'subing_strategy_15m_v1'
    || payload.series_kind !== 'actual_dominant'
    || payload.frequency !== '15m'
    || !SUBING_STRATEGY_PERFORMANCE_CACHE_STATES.includes(payload.cache_state as never)
    || !Array.isArray(payload.episodes)
    || !Array.isArray(payload.exit_reason_counts)
    || typeof payload.symbol !== 'string'
    || payload.symbol !== payload.symbol.toLowerCase()
    || strategyDate(coverage.since) > strategyDate(coverage.through)
    || !Number.isFinite(Date.parse(strategyTimestamp(coverage.resolved_cutoff)))
    || strategyNonnegativeInteger(coverage.segment_count) === 0
    || strategyNonnegativeInteger(coverage.bar_count_15m) === 0
    || strategyNonnegativeInteger(coverage.context_unavailable_count) < 0
    || !summary.overall || !summary.long || !summary.short
    || (
      payload.cache_state !== 'unavailable'
      && (
        typeof payload.cache_identity_sha256 !== 'string'
        || !/^[0-9a-f]{64}$/.test(payload.cache_identity_sha256)
        || typeof payload.cache_generated_at !== 'string'
        || !Number.isFinite(Date.parse(payload.cache_generated_at))
      )
    )
    || (
      payload.cache_state === 'unavailable'
      && (
        payload.cache_generated_at !== null
        || (
          payload.cache_identity_sha256 !== null
          && (
            typeof payload.cache_identity_sha256 !== 'string'
            || !/^[0-9a-f]{64}$/.test(payload.cache_identity_sha256)
          )
        )
      )
    )
  ) invalidSubingStrategyResponse()
  const episodes = payload.episodes.map((episode) => (
    normalizeStrategyEpisode(episode, payload.symbol as string)
  ))
  const overall = normalizeSubingStrategyPerformanceStats(summary.overall)
  const long = normalizeSubingStrategyPerformanceStats(summary.long)
  const short = normalizeSubingStrategyPerformanceStats(summary.short)
  const openEpisodes = strategyNonnegativeInteger(summary.open_episodes)
  const exitReasonCounts = payload.exit_reason_counts.map((item) => {
    const reason = strategyRecord(item)
    const count = strategyNonnegativeInteger(reason.count)
    if (count === 0) invalidSubingStrategyResponse()
    return { reason_code: strategyString(reason.reason_code), count }
  })
  const expectedExitReasonCounts = new Map<string, number>()
  for (const episode of episodes) {
    for (const reasonCode of episode.exit_reason_codes) {
      expectedExitReasonCounts.set(
        reasonCode,
        (expectedExitReasonCounts.get(reasonCode) ?? 0) + 1,
      )
    }
  }
  const closedLong = episodes.filter((episode) => (
    episode.state === 'closed' && episode.direction === 'long'
  )).length
  const closedShort = episodes.filter((episode) => (
    episode.state === 'closed' && episode.direction === 'short'
  )).length
  if (
    overall.completed !== long.completed + short.completed
    || overall.positive !== long.positive + short.positive
    || overall.negative !== long.negative + short.negative
    || overall.flat !== long.flat + short.flat
    || overall.completed + openEpisodes !== episodes.length
    || long.completed !== closedLong
    || short.completed !== closedShort
    || new Set(exitReasonCounts.map((item) => item.reason_code)).size
      !== exitReasonCounts.length
    || exitReasonCounts.length !== expectedExitReasonCounts.size
    || exitReasonCounts.some((item) => (
      expectedExitReasonCounts.get(item.reason_code) !== item.count
    ))
  ) invalidSubingStrategyResponse()
  return {
    ...(payload as unknown as SubingStrategyPerformanceResponse),
    coverage: {
      since: strategyDate(coverage.since),
      through: strategyDate(coverage.through),
      resolved_cutoff: strategyTimestamp(coverage.resolved_cutoff),
      segment_count: strategyNonnegativeInteger(coverage.segment_count),
      bar_count_15m: strategyNonnegativeInteger(coverage.bar_count_15m),
      context_unavailable_count: strategyNonnegativeInteger(
        coverage.context_unavailable_count,
      ),
    },
    summary: { overall, long, short, open_episodes: openEpisodes },
    exit_reason_counts: exitReasonCounts,
    episodes,
  }
}

export function normalizeSubingStrategyCurrent(value: unknown): SubingStrategyCurrentResponse {
  const payload = strategyRecord(value)
  if (
    payload.strategy_id !== 'subing_strategy_v1'
    || payload.formula_version !== 'subing_strategy_15m_v1'
    || payload.series_kind !== 'actual_dominant'
    || payload.frequency !== '15m'
    || !['canonical', 'canonical_live'].includes(String(payload.source_mode))
    || !['flat', 'long', 'short'].includes(String(payload.position_state))
  ) invalidSubingStrategyResponse()
  const symbol = strategyString(payload.symbol)
  const contract = strategyString(payload.contract)
  if (symbol !== symbol.toLowerCase() || !contract.startsWith(symbol.toUpperCase())) {
    invalidSubingStrategyResponse()
  }
  strategyDate(payload.segment_start_trading_day)
  strategyTimestamp(payload.cutoff)
  const currentEpisode = payload.current_episode === null
    ? null : normalizeStrategyEpisode(payload.current_episode, symbol)
  const latestCompleted = payload.latest_completed_episode === null
    ? null : normalizeStrategyEpisode(payload.latest_completed_episode, symbol)
  const pending = payload.pending_action === null ? null : strategyRecord(payload.pending_action)
  const normalizedPending = pending === null ? null : {
    kind: strategyEnum(pending.kind, SUBING_STRATEGY_ACTION_KINDS),
    decision_at: strategyTimestamp(pending.decision_at),
    opportunity_id: strategyString(pending.opportunity_id),
    reason_codes: strategyStringArray(pending.reason_codes),
  }
  const context = strategyRecord(payload.direction_context)
  const contextDirection = strategyEnum(context.direction, [
    'long_only', 'short_only', 'no_new_entry', 'unavailable',
  ] as const)
  const sourceTradingDay = context.source_trading_day === null
    ? null : strategyDate(context.source_trading_day)
  const dailyBarEnd = context.daily_bar_end === null
    ? null : strategyTimestamp(context.daily_bar_end)
  const hourlyBarEnd = context.hourly_bar_end === null
    ? null : strategyTimestamp(context.hourly_bar_end)
  const physicalContract = context.physical_contract === null
    ? null : strategyString(context.physical_contract)
  if (
    (payload.position_state === 'flat' && currentEpisode !== null)
    || (payload.position_state !== 'flat' && currentEpisode?.state !== 'open')
    || latestCompleted?.state === 'open'
    || context.symbol !== symbol
    || (payload.position_state === 'long' && currentEpisode?.direction !== 'long')
    || (payload.position_state === 'short' && currentEpisode?.direction !== 'short')
    || (currentEpisode !== null && currentEpisode.entry_action.contract !== contract)
    || (latestCompleted !== null && latestCompleted.entry_action.contract !== contract)
    || (physicalContract !== null && physicalContract !== contract)
  ) invalidSubingStrategyResponse()
  return {
    ...(payload as unknown as SubingStrategyCurrentWireResponse),
    pending_action: normalizedPending,
    current_episode: currentEpisode,
    latest_completed_episode: latestCompleted,
    direction_context: {
      symbol,
      target_trading_day: strategyDate(context.target_trading_day),
      source_trading_day: sourceTradingDay,
      direction: contextDirection,
      reason_codes: strategyStringArray(context.reason_codes),
      daily_bar_end: dailyBarEnd,
      hourly_bar_end: hourlyBarEnd,
      physical_contract: physicalContract,
    },
  }
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
  action_id: null
  strategy_action: null
}

export interface SubingStrategyAlertEventCommon extends AlertEventCommon {
  rule_code: 'subing_strategy_v1'
  trading_day: string
  frequency: '15m'
  action_id: string
}

export type SubingStrategyAlertEvent = SubingStrategyAlertEventCommon & (
  | {
      result_codes: ['open_long']
      strategy_action: SubingStrategyOpenLongActionPayloadWire
    }
  | {
      result_codes: ['open_short']
      strategy_action: SubingStrategyOpenShortActionPayloadWire
    }
  | {
      result_codes: ['close_long']
      strategy_action: SubingStrategyCloseLongActionPayloadWire
    }
  | {
      result_codes: ['close_short']
      strategy_action: SubingStrategyCloseShortActionPayloadWire
    }
)

/** Exact Alert HTTP union discriminated by the registered Rule identity. */
export type AlertEvent = HtdyAlertEvent | SubingStrategyAlertEvent

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
