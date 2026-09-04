import type {
  NewowBar,
  NewowCleanroomCompositeDecision,
  NewowCompositeDecision,
  NewowCupDirection,
  NewowCupHandle,
  NewowCupMarkerType,
  NewowCupPivot,
  NewowCupState,
  NewowJsonValue,
  NewowMarker,
  NewowMarkerType,
  NewowPageWindowComparison,
  NewowPriceChannel,
  NewowRolloverSeam,
  NewowTrendBandPoint,
  NewowTrendDetailResponse,
  NewowTrendMarkerType,
  NewowTrendQueryIdentity,
  NewowWarning,
} from '../types/newow.ts'

const STRATEGY_CODE = 'newow_trend_v1'
const PROFILE_ID = 'newow_trend_d1_page_v2'
const TREND_FORMULA = 'newow_trend_band_page_v2'
const ESCAPE_FORMULA = 'newow_escape_d123_page_v2'
const CUP_FORMULA = 'newow_cup_handle_v1'
const OSCILLATION_FORMULA = 'newow_oscillation_hhv_llv10_page_v1'
const MAIN_FORCE_FORMULA = 'newow_main_force_control_page_v1'
const MAIN_RISE_FORMULA = 'newow_main_rise_ma35_ma45_page_v1'
const CHANNEL_FORMULA = 'newow_target_absorb_hhv_llv10_page_v1'
const DISPLAY_FORMULA = 'newow_target_absorb_display_selection_page_v1'
const PAGE_WINDOW_FORMULA = 'newow_hhv_llv_window_optimizer_page_v1'
const CAUSAL_WINDOW_FORMULA = 'newow_hhv_llv_window_optimizer_causal_v1'
const PAGE_COMPOSITE_FORMULA = 'newow_composite_decision_page_v3_2_82'
const CLEANROOM_COMPOSITE_FORMULA = 'newow_composite_decision_cleanroom_v1'
const FIRST_ACTION_FORMULA = 'newow_first_action_principle_page_v3_2_63'
const DIAGNOSTIC_FACTS_FORMULA = 'newow_diagnostic_facts_cleanroom_v1'
const DIAGNOSTIC_RULES_FORMULA = 'newow_diagnostic_rules_cleanroom_v1'
const FORMULA_VERSIONS = [
  TREND_FORMULA, ESCAPE_FORMULA, CUP_FORMULA, OSCILLATION_FORMULA,
  MAIN_FORCE_FORMULA, MAIN_RISE_FORMULA, CHANNEL_FORMULA, DISPLAY_FORMULA,
  PAGE_WINDOW_FORMULA, CAUSAL_WINDOW_FORMULA, PAGE_COMPOSITE_FORMULA,
  CLEANROOM_COMPOSITE_FORMULA, FIRST_ACTION_FORMULA, DIAGNOSTIC_FACTS_FORMULA,
  DIAGNOSTIC_RULES_FORMULA,
] as const

const TOP_LEVEL_KEYS = [
  'meta', 'instrument', 'bars', 'bar_policy', 'trend_band', 'trend_markers',
  'escape_markers', 'cup_markers', 'cup_handles', 'rollover_seams', 'legend',
  'price_channel', 'page_window_comparison', 'composite_page', 'composite_cleanroom',
  'first_action_principle', 'diagnostic_facts', 'diagnostic_tokens', 'semantic_labels',
  'formula_descriptions', 'warnings',
] as const
const TREND_STATES = ['UNAVAILABLE', 'YELLOW', 'BLUE'] as const
const PRIOR_TREND_STATES = ['YELLOW', 'BLUE'] as const
const TREND_TRANSITIONS = ['BUILD', 'CLEAR'] as const
const TREND_MARKERS = ['BUILD', 'CLEAR'] as const
const ESCAPE_MARKERS = ['NEWOW_ESCAPE_D1', 'NEWOW_ESCAPE_D2', 'NEWOW_ESCAPE_D3'] as const
const CUP_MARKERS = [
  'CUP_HANDLE_READY', 'CUP_HANDLE_BREAKOUT', 'CUP_HANDLE_WEAKENED',
  'CUP_HANDLE_INVALIDATED', 'CUP_HANDLE_EXPIRED',
] as const
const CUP_DIRECTIONS = ['BULLISH', 'BEARISH'] as const
const CUP_STATES = ['FORMING', 'READY', 'BREAKOUT', 'WEAKENED', 'INVALIDATED', 'EXPIRED'] as const
const WARNINGS = [
  'NEWOW_TREND_WARMUP_INSUFFICIENT',
  'NEWOW_D123_WARMUP_INSUFFICIENT',
  'NEWOW_CUP_WARMUP_INSUFFICIENT',
  'NEWOW_COMPOSITE_DAILY_BARS_INSUFFICIENT',
] as const
const DISPLAY_PERIODS = ['day', 'week', 'best_available'] as const
const TREND_BIASES = ['bullish', 'bearish', 'cautious', 'warning', 'neutral'] as const
const OSCILLATION_BIASES = ['bullish', 'bearish', 'neutral'] as const
const DIRECTION_TOKENS = [
  'weekly_bearish_rebound', 'weekly_bearish', 'daily_pullback',
  'sixty_minute_pullback', 'multiperiod_bullish', 'insufficient',
] as const
const ACTION_TOKENS = [
  'BUILD_OR_ADD', 'HOLD_AND_WAIT', 'REDUCE_AND_WAIT', 'CLEAR',
  'CAUTIOUS_HOLD', 'WAIT_FOR_SIGNAL',
] as const
const DECISION_KEYS = [
  'bullish-bullish', 'bullish-bearish', 'bullish-neutral',
  'bearish-bullish', 'bearish-bearish', 'bearish-neutral',
  'cautious-bullish', 'cautious-bearish', 'cautious-neutral',
  'warning-bullish', 'warning-bearish', 'warning-neutral', 'neutral-neutral',
] as const
const UNREACHABLE_DECISION_KEYS = ['neutral-bullish', 'neutral-bearish', 'neutral-warning'] as const
const PAGE_WINDOWS = [10, 20, 24, 30, 52] as const
const FORMING_SCORE_KEYS = ['pretrend', 'cup_geometry', 'u_shape_purity'] as const
const COMPLETE_SCORE_KEYS = [...FORMING_SCORE_KEYS, 'handle_quality', 'volume_structure'] as const
const VOLUME_FACT_KEYS = [
  'right_leg_median', 'handle_median', 'handle_baseline_median',
  'handle_right_ratio', 'handle_baseline_ratio',
] as const
const DECIMAL_PATTERN = /^([+-])?(?:(\d+)(?:\.(\d*))?|\.(\d+))(?:[eE]([+-]?\d+))?$/

export function normalizeNewowTrendDetailResponse(
  payload: unknown,
  expected: NewowTrendQueryIdentity,
): NewowTrendDetailResponse {
  const identity = normalizeExpectedIdentity(expected)
  const value = exactRecord(payload, 'Newow trend detail', TOP_LEVEL_KEYS)
  const meta = normalizeMeta(value.meta, identity)
  const instrument = normalizeInstrument(value.instrument, identity.symbol)
  const bars = array(value.bars, 'bars').map((bar, index) => normalizeBar(bar, index, meta.calculation_identity))
  validateBars(bars, identity)
  if (instrument.last_visible_physical_contract !== (bars.at(-1)?.physical_contract ?? null)) {
    throw new Error('last_visible_physical_contract disagrees with visible bars')
  }
  const trendBand = array(value.trend_band, 'trend_band').map(normalizeTrendBandPoint)
  validateTrendBand(trendBand, bars)
  const trendMarkers = normalizeMarkers(
    value.trend_markers,
    'trend_markers',
    TREND_MARKERS,
    TREND_FORMULA,
    bars,
    'trend_slow_band',
    trendBand,
  )
  const escapeMarkers = normalizeMarkers(
    value.escape_markers,
    'escape_markers',
    ESCAPE_MARKERS,
    ESCAPE_FORMULA,
    bars,
    'high',
  )
  const cupMarkers = normalizeMarkers(
    value.cup_markers,
    'cup_markers',
    CUP_MARKERS,
    CUP_FORMULA,
    bars,
    'close',
  )
  validateGlobalMarkers([...trendMarkers, ...escapeMarkers, ...cupMarkers])
  validateTrendTransitions(trendBand, trendMarkers)
  const cupHandles = array(value.cup_handles, 'cup_handles').map(normalizeCupHandle)
  validateCupHandles(cupHandles, cupMarkers, bars)
  const rolloverSeams = array(value.rollover_seams, 'rollover_seams').map(normalizeRolloverSeam)
  validateRolloverSeams(rolloverSeams, bars)
  const priceChannel = normalizePriceChannel(value.price_channel, bars)
  const pageWindowComparison = normalizePageWindowComparison(value.page_window_comparison)
  const compositePage = value.composite_page === null
    ? null : normalizeComposite(value.composite_page, 'composite_page', true)
  const compositeCleanroom = value.composite_cleanroom === null
    ? null : normalizeComposite(value.composite_cleanroom, 'composite_cleanroom', false)
  if ((compositePage === null) !== (compositeCleanroom === null)) {
    throw new Error('page and clean-room composites must be available together')
  }
  const firstActionPrinciple = normalizeFirstAction(value.first_action_principle)
  const diagnosticFacts = normalizeDiagnosticFacts(value.diagnostic_facts, bars, priceChannel)
  const diagnosticTokens = normalizeDiagnosticTokens(value.diagnostic_tokens)
  const semanticLabels = normalizeSemanticLabels(value.semantic_labels)
  const warnings = normalizeWarnings(
    value.warnings, bars, trendBand, compositePage === null,
  )

  if (value.bar_policy !== 'completed_only') throw new Error('bar_policy must be completed_only')
  const legend = exactRecord(value.legend, 'legend', ['BUILD', 'CLEAR', 'D1', 'D2', 'D3'])
  requireExact(legend.BUILD, 'trend build', 'legend.BUILD')
  requireExact(legend.CLEAR, 'trend clear', 'legend.CLEAR')
  requireExact(legend.D1, 'escape D1', 'legend.D1')
  requireExact(legend.D2, 'escape D2', 'legend.D2')
  requireExact(legend.D3, 'escape D3', 'legend.D3')
  const descriptions = exactRecord(
    value.formula_descriptions,
    'formula_descriptions',
    [
      'trend_band', 'escape', 'cup_handle', 'oscillation', 'main_force', 'main_rise',
      'price_channel', 'display_selection', 'page_window_comparison',
      'causal_window_identity', 'composite_page', 'composite_cleanroom',
      'first_action', 'diagnostic_facts', 'diagnostic_rules',
    ],
  )
  requireExact(descriptions.trend_band, TREND_FORMULA, 'formula_descriptions.trend_band')
  requireExact(descriptions.escape, ESCAPE_FORMULA, 'formula_descriptions.escape')
  requireExact(descriptions.cup_handle, CUP_FORMULA, 'formula_descriptions.cup_handle')
  requireExact(descriptions.oscillation, OSCILLATION_FORMULA, 'formula_descriptions.oscillation')
  requireExact(descriptions.main_force, MAIN_FORCE_FORMULA, 'formula_descriptions.main_force')
  requireExact(descriptions.main_rise, MAIN_RISE_FORMULA, 'formula_descriptions.main_rise')
  requireExact(descriptions.price_channel, CHANNEL_FORMULA, 'formula_descriptions.price_channel')
  requireExact(descriptions.display_selection, DISPLAY_FORMULA, 'formula_descriptions.display_selection')
  requireExact(descriptions.page_window_comparison, PAGE_WINDOW_FORMULA, 'formula_descriptions.page_window_comparison')
  requireExact(descriptions.causal_window_identity, CAUSAL_WINDOW_FORMULA, 'formula_descriptions.causal_window_identity')
  requireExact(descriptions.composite_page, PAGE_COMPOSITE_FORMULA, 'formula_descriptions.composite_page')
  requireExact(descriptions.composite_cleanroom, CLEANROOM_COMPOSITE_FORMULA, 'formula_descriptions.composite_cleanroom')
  requireExact(descriptions.first_action, FIRST_ACTION_FORMULA, 'formula_descriptions.first_action')
  requireExact(descriptions.diagnostic_facts, DIAGNOSTIC_FACTS_FORMULA, 'formula_descriptions.diagnostic_facts')
  requireExact(descriptions.diagnostic_rules, DIAGNOSTIC_RULES_FORMULA, 'formula_descriptions.diagnostic_rules')

  return deepFreeze({
    meta,
    instrument,
    bars,
    bar_policy: 'completed_only',
    trend_band: trendBand,
    trend_markers: trendMarkers,
    escape_markers: escapeMarkers,
    cup_markers: cupMarkers,
    cup_handles: cupHandles,
    rollover_seams: rolloverSeams,
    price_channel: priceChannel,
    page_window_comparison: pageWindowComparison,
    composite_page: compositePage,
    composite_cleanroom: compositeCleanroom,
    first_action_principle: firstActionPrinciple,
    diagnostic_facts: diagnosticFacts,
    diagnostic_tokens: diagnosticTokens,
    semantic_labels: semanticLabels,
    legend: {
      BUILD: 'trend build', CLEAR: 'trend clear', D1: 'escape D1',
      D2: 'escape D2', D3: 'escape D3',
    },
    formula_descriptions: {
      trend_band: TREND_FORMULA, escape: ESCAPE_FORMULA, cup_handle: CUP_FORMULA,
      oscillation: OSCILLATION_FORMULA, main_force: MAIN_FORCE_FORMULA,
      main_rise: MAIN_RISE_FORMULA, price_channel: CHANNEL_FORMULA,
      display_selection: DISPLAY_FORMULA, page_window_comparison: PAGE_WINDOW_FORMULA,
      causal_window_identity: CAUSAL_WINDOW_FORMULA, composite_page: PAGE_COMPOSITE_FORMULA,
      composite_cleanroom: CLEANROOM_COMPOSITE_FORMULA, first_action: FIRST_ACTION_FORMULA,
      diagnostic_facts: DIAGNOSTIC_FACTS_FORMULA, diagnostic_rules: DIAGNOSTIC_RULES_FORMULA,
    },
    warnings,
  })
}

function normalizeExpectedIdentity(expected: NewowTrendQueryIdentity): NewowTrendQueryIdentity {
  const value = exactRecord(expected, 'expected query identity', ['symbol', 'from', 'through'])
  const symbol = text(value.symbol, 'symbol')
  if (!/^[a-z]+$/.test(symbol)) throw new Error('symbol must be a lowercase product code')
  const from = day(value.from, 'from')
  const through = day(value.through, 'through')
  if (from > through) throw new Error('from must not be after through')
  return { symbol, from, through }
}

function normalizeMeta(payload: unknown, expected: NewowTrendQueryIdentity): NewowTrendDetailResponse['meta'] {
  const value = exactRecord(payload, 'meta', [
    'strategy_code', 'profile_id', 'frequency', 'series_kind', 'calculation_identity',
    'data_revision_identity', 'request_identity',
  ])
  requireExact(value.strategy_code, STRATEGY_CODE, 'meta.strategy_code')
  requireExact(value.profile_id, PROFILE_ID, 'meta.profile_id')
  requireExact(value.frequency, '1d', 'meta.frequency')
  requireExact(value.series_kind, 'actual_dominant', 'meta.series_kind')
  const expectedCalculation = [
    'market_data_service:canonical_v2',
    'main_contract_map:rank1:canonical_v1',
    expected.symbol,
    'actual_dominant',
    '1d+1w+60m',
    PROFILE_ID,
    ...FORMULA_VERSIONS,
  ].join('|')
  requireExact(value.calculation_identity, expectedCalculation, 'meta.calculation_identity')
  const dataRevisionIdentity = nullableText(value.data_revision_identity, 'meta.data_revision_identity')
  const expectedRequest = `${expectedCalculation}:${expected.from}:${expected.through}`
  requireExact(value.request_identity, expectedRequest, 'meta.request_identity')
  return {
    strategy_code: STRATEGY_CODE,
    profile_id: PROFILE_ID,
    frequency: '1d',
    series_kind: 'actual_dominant',
    calculation_identity: expectedCalculation,
    data_revision_identity: dataRevisionIdentity,
    request_identity: expectedRequest,
  }
}

function normalizeInstrument(payload: unknown, expectedProduct: string): NewowTrendDetailResponse['instrument'] {
  const value = exactRecord(payload, 'instrument', ['product', 'display_name', 'last_visible_physical_contract'])
  requireExact(value.product, expectedProduct, 'instrument.product')
  return {
    product: expectedProduct,
    display_name: nullableText(value.display_name, 'instrument.display_name'),
    last_visible_physical_contract: nullableContract(value.last_visible_physical_contract, 'instrument.last_visible_physical_contract'),
  }
}

function normalizeBar(payload: unknown, index: number, calculationIdentity: string): NewowBar {
  const field = `bars[${index}]`
  const value = exactRecord(payload, field, [
    'bar_end', 'trading_day', 'open', 'high', 'low', 'close', 'volume', 'open_interest',
    'physical_contract', 'segment_id', 'source_identity',
  ])
  const open = positiveDecimal(value.open, `${field}.open`)
  const high = positiveDecimal(value.high, `${field}.high`)
  const low = positiveDecimal(value.low, `${field}.low`)
  const close = positiveDecimal(value.close, `${field}.close`)
  if (low > high || open < low || open > high || close < low || close > high) {
    throw new Error(`${field} has invalid OHLC ordering`)
  }
  requireExact(value.source_identity, calculationIdentity, `${field}.source_identity`)
  return {
    bar_end: instant(value.bar_end, `${field}.bar_end`),
    trading_day: day(value.trading_day, `${field}.trading_day`),
    open,
    high,
    low,
    close,
    volume: nonNegativeInteger(value.volume, `${field}.volume`),
    open_interest: value.open_interest === null ? null : nonNegativeInteger(value.open_interest, `${field}.open_interest`),
    physical_contract: contract(value.physical_contract, `${field}.physical_contract`),
    segment_id: text(value.segment_id, `${field}.segment_id`),
    source_identity: calculationIdentity,
  }
}

function validateBars(bars: readonly NewowBar[], expected: NewowTrendQueryIdentity): void {
  for (let index = 0; index < bars.length; index += 1) {
    const bar = bars[index]!
    if (bar.trading_day < expected.from || bar.trading_day > expected.through) {
      throw new Error(`bars[${index}].trading_day is outside the request window`)
    }
    if (index === 0) continue
    const previous = bars[index - 1]!
    if (bar.trading_day <= previous.trading_day || instantValue(bar.bar_end) <= instantValue(previous.bar_end)) {
      throw new Error('bars must have sorted unique trading days and bar_end values')
    }
    const contractChanged = bar.physical_contract !== previous.physical_contract
    const segmentChanged = bar.segment_id !== previous.segment_id
    if (contractChanged !== segmentChanged) {
      throw new Error('visible physical contract and segment identities are inconsistent')
    }
  }
  const segmentContracts = new Map<string, string>()
  for (const bar of bars) {
    const existing = segmentContracts.get(bar.segment_id)
    if (existing !== undefined && existing !== bar.physical_contract) {
      throw new Error('one visible segment maps to multiple physical contracts')
    }
    segmentContracts.set(bar.segment_id, bar.physical_contract)
  }
}

function normalizeTrendBandPoint(payload: unknown, index: number): NewowTrendBandPoint {
  const field = `trend_band[${index}]`
  const value = exactRecord(payload, field, ['bar_end', 'b_value', 'c_value', 'state', 'state_before', 'transition'])
  const state = literal(value.state, TREND_STATES, `${field}.state`)
  const stateBefore = value.state_before === null
    ? null
    : literal(value.state_before, PRIOR_TREND_STATES, `${field}.state_before`)
  const transition = value.transition === null
    ? null
    : literal(value.transition, TREND_TRANSITIONS, `${field}.transition`)
  const bValue = nullableFinite(value.b_value, `${field}.b_value`)
  const cValue = nullableFinite(value.c_value, `${field}.c_value`)
  if (state === 'UNAVAILABLE') {
    if (cValue !== null || transition !== null) throw new Error(`${field} unavailable state is contradictory`)
  } else if (bValue === null || bValue <= 0 || cValue === null || cValue <= 0) {
    throw new Error(`${field} available state requires positive band values`)
  }
  if (
    (transition === 'BUILD' && (stateBefore !== 'BLUE' || state !== 'YELLOW'))
    || (transition === 'CLEAR' && (stateBefore !== 'YELLOW' || state !== 'BLUE'))
  ) throw new Error(`${field}.transition contradicts its states`)
  if (stateBefore === 'BLUE' && state === 'YELLOW' && transition !== 'BUILD') {
    throw new Error(`${field}.transition is incomplete for its state change`)
  }
  return {
    bar_end: instant(value.bar_end, `${field}.bar_end`),
    b_value: bValue,
    c_value: cValue,
    state,
    state_before: stateBefore,
    transition,
  }
}

function validateTrendBand(points: readonly NewowTrendBandPoint[], bars: readonly NewowBar[]): void {
  if (points.length !== bars.length) throw new Error('trend_band must align exactly with bars')
  for (let index = 0; index < points.length; index += 1) {
    if (points[index]!.bar_end !== bars[index]!.bar_end) {
      throw new Error(`trend_band[${index}] does not reference its visible bar`)
    }
  }
}

function normalizeMarkers<T extends NewowMarkerType>(
  payload: unknown,
  family: string,
  acceptedTypes: readonly T[],
  formulaVersion: string,
  bars: readonly NewowBar[],
  priceBasis: 'close' | 'high' | 'trend_slow_band',
  trendBand: readonly NewowTrendBandPoint[] = [],
): NewowMarker<T>[] {
  const barByEnd = new Map(bars.map((bar, index) => [bar.bar_end, { bar, index }]))
  let priorBarIndex = -1
  return array(payload, family).map((item, index) => {
    const field = `${family}[${index}]`
    const value = exactRecord(item, field, [
      'marker_id', 'marker_type', 'bar_end', 'price', 'label', 'color_token', 'priority',
      'related_marker_ids', 'trigger_facts', 'formula_version',
    ])
    const markerType = literal(value.marker_type, acceptedTypes, `${field}.marker_type`)
    const barEnd = instant(value.bar_end, `${field}.bar_end`)
    const referenced = barByEnd.get(barEnd)
    if (referenced === undefined) throw new Error(`${field}.bar_end must reference a visible bar`)
    if (referenced.index < priorBarIndex) throw new Error(`${family} must be ordered by visible bar`)
    priorBarIndex = referenced.index
    const price = positiveDecimal(value.price, `${field}.price`)
    const expectedPrice = priceBasis === 'high'
      ? referenced.bar.high
      : priceBasis === 'trend_slow_band'
        ? trendBand[referenced.index]?.c_value
        : referenced.bar.close
    if (expectedPrice === null || expectedPrice === undefined || price !== expectedPrice) {
      throw new Error(`${field}.price disagrees with ${priceBasis}`)
    }
    requireExact(value.formula_version, formulaVersion, `${field}.formula_version`)
    const markerId = text(value.marker_id, `${field}.marker_id`)
    const relatedMarkerIds = stringArray(value.related_marker_ids, `${field}.related_marker_ids`, true)
    if (relatedMarkerIds.includes(markerId)) throw new Error(`${field} cannot relate to itself`)
    return {
      marker_id: markerId,
      marker_type: markerType,
      bar_end: barEnd,
      price,
      label: text(value.label, `${field}.label`),
      color_token: text(value.color_token, `${field}.color_token`),
      priority: nonNegativeInteger(value.priority, `${field}.priority`),
      related_marker_ids: relatedMarkerIds,
      trigger_facts: jsonRecord(value.trigger_facts, `${field}.trigger_facts`),
      formula_version: formulaVersion,
    }
  })
}

function validateGlobalMarkers(markers: readonly NewowMarker[]): void {
  if (new Set(markers.map((marker) => marker.marker_id)).size !== markers.length) {
    throw new Error('Newow marker_id values must be globally unique')
  }
}

function validateTrendTransitions(
  points: readonly NewowTrendBandPoint[],
  markers: readonly NewowMarker<NewowTrendMarkerType>[],
): void {
  const counts = new Map<string, number>()
  for (const marker of markers) {
    const point = points.find((candidate) => candidate.bar_end === marker.bar_end)
    if (point?.transition !== marker.marker_type) throw new Error('trend marker contradicts the aligned transition')
    const key = `${marker.bar_end}|${marker.marker_type}`
    counts.set(key, (counts.get(key) ?? 0) + 1)
  }
  for (const point of points) {
    if (point.transition === null) continue
    if (counts.get(`${point.bar_end}|${point.transition}`) !== 1) {
      throw new Error('every trend transition must have exactly one aligned trend marker')
    }
  }
}

function normalizeCupHandle(payload: unknown, index: number): NewowCupHandle {
  const field = `cup_handles[${index}]`
  const value = exactRecord(payload, field, [
    'candidate_id', 'direction', 'state', 'left_rim', 'bottom', 'right_rim',
    'handle_start_at', 'handle_extreme', 'pivot_price', 'pivot_frozen_at', 'confirmed_at',
    'first_seen_at', 'state_changed_at', 'score', 'score_breakdown', 'hard_failures',
    'diagnostics', 'volume_facts', 'formula_version',
  ])
  const state = literal(value.state, CUP_STATES, `${field}.state`)
  const leftRim = normalizePivot(value.left_rim, `${field}.left_rim`)
  const bottom = normalizePivot(value.bottom, `${field}.bottom`)
  const rightRim = normalizePivot(value.right_rim, `${field}.right_rim`)
  if (!(instantValue(leftRim.pivot_at) < instantValue(bottom.pivot_at)
    && instantValue(bottom.pivot_at) < instantValue(rightRim.pivot_at))) {
    throw new Error(`${field} pivot timestamps must be strictly ordered`)
  }
  const handleStartAt = instant(value.handle_start_at, `${field}.handle_start_at`)
  if (handleStartAt !== rightRim.pivot_at) throw new Error(`${field}.handle_start_at must equal right_rim.pivot_at`)
  const handleExtreme = value.handle_extreme === null ? null : normalizePivot(value.handle_extreme, `${field}.handle_extreme`)
  if (handleExtreme !== null && instantValue(handleExtreme.pivot_at) <= instantValue(rightRim.pivot_at)) {
    throw new Error(`${field}.handle_extreme must follow the right rim`)
  }
  const pivotPrice = value.pivot_price === null ? null : positiveDecimal(value.pivot_price, `${field}.pivot_price`)
  const pivotFrozenAt = value.pivot_frozen_at === null ? null : instant(value.pivot_frozen_at, `${field}.pivot_frozen_at`)
  const confirmedAt = instant(value.confirmed_at, `${field}.confirmed_at`)
  const firstSeenAt = instant(value.first_seen_at, `${field}.first_seen_at`)
  const stateChangedAt = instant(value.state_changed_at, `${field}.state_changed_at`)
  const readyFacts = handleExtreme !== null && pivotPrice !== null && pivotFrozenAt !== null
  if ((state === 'FORMING' && readyFacts) || (state !== 'FORMING' && !readyFacts)) {
    throw new Error(`${field} state contradicts its ready facts`)
  }
  if (state === 'FORMING' && (handleExtreme !== null || pivotPrice !== null || pivotFrozenAt !== null)) {
    throw new Error(`${field} FORMING state must not expose frozen pivot facts`)
  }
  if (pivotFrozenAt !== null && pivotFrozenAt !== confirmedAt) {
    throw new Error(`${field}.pivot_frozen_at must equal confirmed_at`)
  }
  const anchorConfirmedAt = Math.max(
    instantValue(leftRim.confirmed_at),
    instantValue(bottom.confirmed_at),
    instantValue(rightRim.confirmed_at),
  )
  if (instantValue(firstSeenAt) < anchorConfirmedAt) throw new Error(`${field}.first_seen_at precedes an anchor confirmation`)
  if (state === 'FORMING') {
    if (
      instantValue(confirmedAt) !== anchorConfirmedAt
      || instantValue(firstSeenAt) < instantValue(confirmedAt)
      || instantValue(stateChangedAt) !== instantValue(firstSeenAt)
    ) throw new Error(`${field} FORMING lifecycle timestamps are contradictory`)
  } else {
    const readyConfirmedAt = Math.max(anchorConfirmedAt, instantValue(handleExtreme!.confirmed_at))
    if (
      instantValue(confirmedAt) < readyConfirmedAt
      || instantValue(firstSeenAt) > instantValue(confirmedAt)
      || instantValue(stateChangedAt) < instantValue(confirmedAt)
      || (state === 'READY' && instantValue(stateChangedAt) !== instantValue(confirmedAt))
    ) throw new Error(`${field} ready lifecycle timestamps are contradictory`)
  }

  const scoreBreakdown = finiteMap(value.score_breakdown, `${field}.score_breakdown`, COMPLETE_SCORE_KEYS)
  const volumeFacts = finiteMap(
    value.volume_facts,
    `${field}.volume_facts`,
    state === 'FORMING' ? [] : VOLUME_FACT_KEYS,
  )
  const score = boundedNumber(value.score, `${field}.score`, 0, 100)
  const scoreTotal = Object.values(scoreBreakdown).reduce((total, item) => total + item, 0)
  if (Math.abs(score - scoreTotal) > 1e-9) throw new Error(`${field}.score disagrees with score_breakdown`)
  if (state === 'FORMING' && (scoreBreakdown.handle_quality !== 0 || scoreBreakdown.volume_structure !== 0)) {
    throw new Error(`${field} FORMING score_breakdown requires zero handle and volume scores`)
  }
  const hardFailures = stringArray(value.hard_failures, `${field}.hard_failures`, false)
  if (hardFailures.length !== 0) throw new Error(`${field}.hard_failures must be empty for a public overlay`)
  requireExact(value.formula_version, CUP_FORMULA, `${field}.formula_version`)
  return {
    candidate_id: text(value.candidate_id, `${field}.candidate_id`),
    direction: literal(value.direction, CUP_DIRECTIONS, `${field}.direction`) as NewowCupDirection,
    state: state as NewowCupState,
    left_rim: leftRim,
    bottom,
    right_rim: rightRim,
    handle_start_at: handleStartAt,
    handle_extreme: handleExtreme,
    pivot_price: pivotPrice,
    pivot_frozen_at: pivotFrozenAt,
    confirmed_at: confirmedAt,
    first_seen_at: firstSeenAt,
    state_changed_at: stateChangedAt,
    score,
    score_breakdown: scoreBreakdown,
    hard_failures: hardFailures,
    diagnostics: stringArray(value.diagnostics, `${field}.diagnostics`, false),
    volume_facts: volumeFacts,
    formula_version: CUP_FORMULA,
  }
}

function normalizePivot(payload: unknown, field: string): NewowCupPivot {
  const value = exactRecord(payload, field, ['pivot_at', 'confirmed_at', 'price'])
  const pivotAt = instant(value.pivot_at, `${field}.pivot_at`)
  const confirmedAt = instant(value.confirmed_at, `${field}.confirmed_at`)
  if (instantValue(confirmedAt) < instantValue(pivotAt)) throw new Error(`${field}.confirmed_at precedes pivot_at`)
  return { pivot_at: pivotAt, confirmed_at: confirmedAt, price: positiveDecimal(value.price, `${field}.price`) }
}

function validateCupHandles(
  handles: readonly NewowCupHandle[],
  markers: readonly NewowMarker<NewowCupMarkerType>[],
  bars: readonly NewowBar[],
): void {
  const ids = handles.map((handle) => handle.candidate_id)
  if (new Set(ids).size !== ids.length) throw new Error('cup candidate_id values must be unique')
  if (ids.some((id, index) => index > 0 && id <= ids[index - 1]!)) {
    throw new Error('cup_handles must be ordered by candidate_id')
  }
  const lastBarAt = bars.length === 0 ? null : instantValue(bars.at(-1)!.bar_end)
  if (lastBarAt === null && handles.length > 0) throw new Error('cup_handles require visible bars')
  const known = new Set(ids)
  const markerSegments = new Map<string, Set<string>>()
  const barByEnd = new Map(bars.map((bar) => [instantValue(bar.bar_end), bar]))
  for (const marker of markers) {
    const candidateId = marker.trigger_facts.candidate_id
    if (typeof candidateId !== 'string' || !known.has(candidateId)) {
      throw new Error('cup marker must reference a returned cup candidate')
    }
    const bar = barByEnd.get(instantValue(marker.bar_end))
    if (bar === undefined) throw new Error('cup marker must match a visible bar_end')
    const segments = markerSegments.get(candidateId) ?? new Set<string>()
    segments.add(bar.segment_id)
    markerSegments.set(candidateId, segments)
  }
  const firstBarAt = bars.length === 0 ? null : instantValue(bars[0]!.bar_end)
  for (const handle of handles) {
    if (lastBarAt !== null && instantValue(handle.state_changed_at) > lastBarAt) {
      throw new Error('cup handle state_changed_at is after the visible window')
    }
    const segments = new Set(markerSegments.get(handle.candidate_id) ?? [])
    for (const timestamp of cupTimestamps(handle)) {
      const bar = barByEnd.get(instantValue(timestamp))
      if (bar !== undefined) {
        segments.add(bar.segment_id)
      } else if (
        firstBarAt !== null && lastBarAt !== null
        && instantValue(timestamp) >= firstBarAt && instantValue(timestamp) <= lastBarAt
      ) {
        throw new Error('cup handle timestamp must match a visible bar_end')
      }
    }
    if (segments.size !== 1) throw new Error('cup candidate facts must resolve to exactly one visible segment_id')
  }
}

function cupTimestamps(handle: NewowCupHandle): string[] {
  return [
    handle.left_rim.pivot_at,
    handle.left_rim.confirmed_at,
    handle.bottom.pivot_at,
    handle.bottom.confirmed_at,
    handle.right_rim.pivot_at,
    handle.right_rim.confirmed_at,
    handle.handle_start_at,
    ...(handle.handle_extreme === null
      ? []
      : [handle.handle_extreme.pivot_at, handle.handle_extreme.confirmed_at]),
    ...(handle.pivot_frozen_at === null ? [] : [handle.pivot_frozen_at]),
    handle.confirmed_at,
    handle.first_seen_at,
    handle.state_changed_at,
  ]
}

function normalizeRolloverSeam(payload: unknown, index: number): NewowRolloverSeam {
  const field = `rollover_seams[${index}]`
  const value = exactRecord(payload, field, [
    'trading_day', 'previous_contract', 'next_contract', 'previous_bar_end', 'next_bar_end',
    'previous_segment_id', 'next_segment_id',
  ])
  return {
    trading_day: day(value.trading_day, `${field}.trading_day`),
    previous_contract: contract(value.previous_contract, `${field}.previous_contract`),
    next_contract: contract(value.next_contract, `${field}.next_contract`),
    previous_bar_end: instant(value.previous_bar_end, `${field}.previous_bar_end`),
    next_bar_end: instant(value.next_bar_end, `${field}.next_bar_end`),
    previous_segment_id: text(value.previous_segment_id, `${field}.previous_segment_id`),
    next_segment_id: text(value.next_segment_id, `${field}.next_segment_id`),
  }
}

function validateRolloverSeams(seams: readonly NewowRolloverSeam[], bars: readonly NewowBar[]): void {
  const expected: NewowRolloverSeam[] = []
  for (let index = 1; index < bars.length; index += 1) {
    const previous = bars[index - 1]!
    const next = bars[index]!
    if (previous.segment_id === next.segment_id) continue
    expected.push({
      trading_day: next.trading_day,
      previous_contract: previous.physical_contract,
      next_contract: next.physical_contract,
      previous_bar_end: previous.bar_end,
      next_bar_end: next.bar_end,
      previous_segment_id: previous.segment_id,
      next_segment_id: next.segment_id,
    })
  }
  if (seams.length !== expected.length) throw new Error('rollover_seams do not cover visible contract changes exactly')
  for (let index = 0; index < seams.length; index += 1) {
    const seam = seams[index]!
    const boundary = expected[index]!
    if (Object.keys(boundary).some((key) => seam[key as keyof NewowRolloverSeam] !== boundary[key as keyof NewowRolloverSeam])) {
      throw new Error(`rollover_seams[${index}] contradicts its visible contract boundary`)
    }
  }
}

function normalizePriceChannel(payload: unknown, bars: readonly NewowBar[]): NewowPriceChannel {
  const value = exactRecord(payload, 'price_channel', ['daily', 'weekly', 'sixty_minute', 'display'])
  const daily = normalizeFrequencyChannel(value.daily, 'price_channel.daily', '1d')
  const weekly = normalizeFrequencyChannel(value.weekly, 'price_channel.weekly', '1w')
  const sixtyMinute = normalizeFrequencyChannel(value.sixty_minute, 'price_channel.sixty_minute', '60m')
  if (daily.points.length !== bars.length || daily.points.some((point, index) => point.bar_end !== bars[index]!.bar_end)) {
    throw new Error('price_channel.daily must align exactly with visible bars')
  }
  const displayValue = exactRecord(value.display, 'price_channel.display', [
    'target', 'absorb', 'raw_target', 'raw_absorb', 'target_period', 'absorb_period',
    'target_branch_token', 'absorb_branch_token', 'formula_version',
  ])
  requireExact(displayValue.formula_version, DISPLAY_FORMULA, 'price_channel.display.formula_version')
  const display = {
    target: nullableDecimal(displayValue.target, 'price_channel.display.target'),
    absorb: nullableDecimal(displayValue.absorb, 'price_channel.display.absorb'),
    raw_target: nullableDecimal(displayValue.raw_target, 'price_channel.display.raw_target'),
    raw_absorb: nullableDecimal(displayValue.raw_absorb, 'price_channel.display.raw_absorb'),
    target_period: displayValue.target_period === null ? null : literal(displayValue.target_period, DISPLAY_PERIODS, 'price_channel.display.target_period'),
    absorb_period: displayValue.absorb_period === null ? null : literal(displayValue.absorb_period, DISPLAY_PERIODS, 'price_channel.display.absorb_period'),
    target_branch_token: text(displayValue.target_branch_token, 'price_channel.display.target_branch_token'),
    absorb_branch_token: text(displayValue.absorb_branch_token, 'price_channel.display.absorb_branch_token'),
    formula_version: DISPLAY_FORMULA,
  } as const
  if ((display.target === null) !== (display.target_period === null) || (display.absorb === null) !== (display.absorb_period === null)) {
    throw new Error('price_channel.display values and periods must be available together')
  }
  return { daily, weekly, sixty_minute: sixtyMinute, display }
}

function normalizeFrequencyChannel(
  payload: unknown,
  field: string,
  frequency: '1d' | '1w' | '60m',
): NewowPriceChannel['daily'] {
  const value = exactRecord(payload, field, ['frequency', 'points', 'owner_segment_ids', 'formula_version'])
  requireExact(value.frequency, frequency, `${field}.frequency`)
  requireExact(value.formula_version, CHANNEL_FORMULA, `${field}.formula_version`)
  const points = array(value.points, `${field}.points`).map((item, index) => {
    const pointField = `${field}.points[${index}]`
    const point = exactRecord(item, pointField, ['bar_end', 'target', 'absorb', 'window', 'available', 'formula_version'])
    if (point.window !== 10) throw new Error(`${pointField}.window must be 10`)
    requireExact(point.formula_version, CHANNEL_FORMULA, `${pointField}.formula_version`)
    const target = nullableDecimal(point.target, `${pointField}.target`)
    const absorb = nullableDecimal(point.absorb, `${pointField}.absorb`)
    if (typeof point.available !== 'boolean') throw new Error(`${pointField}.available must be boolean`)
    if (point.available !== (target !== null && absorb !== null)) throw new Error(`${pointField}.available contradicts channel values`)
    return {
      bar_end: instant(point.bar_end, `${pointField}.bar_end`), target, absorb,
      window: 10 as const, available: point.available, formula_version: CHANNEL_FORMULA as typeof CHANNEL_FORMULA,
    }
  })
  validateIncreasingInstants(points.map((point) => point.bar_end), `${field}.points`)
  const ownerSegmentIds = stringArray(value.owner_segment_ids, `${field}.owner_segment_ids`, true)
  if (points.length > 0 && ownerSegmentIds.length === 0) throw new Error(`${field} points require owner segments`)
  return { frequency, points, owner_segment_ids: ownerSegmentIds, formula_version: CHANNEL_FORMULA }
}

function normalizePageWindowComparison(payload: unknown): NewowPageWindowComparison[] {
  const items = array(payload, 'page_window_comparison').map((item, index) => {
    const field = `page_window_comparison[${index}]`
    const value = exactRecord(item, field, [
      'window', 'cumulative_return_pct', 'max_drawdown_pct', 'trade_count', 'win_rate_pct',
      'score', 'terminal_position_was_open', 'force_closed_at_end', 'execution_timing',
      'trustworthy_for_research', 'formula_version',
    ])
    if (!PAGE_WINDOWS.includes(value.window as typeof PAGE_WINDOWS[number])) throw new Error(`${field}.window is invalid`)
    if (typeof value.terminal_position_was_open !== 'boolean') throw new Error(`${field}.terminal_position_was_open must be boolean`)
    if (value.force_closed_at_end !== true) throw new Error(`${field}.force_closed_at_end must be true`)
    requireExact(value.execution_timing, 'same_bar_close', `${field}.execution_timing`)
    if (value.trustworthy_for_research !== false) throw new Error(`${field}.trustworthy_for_research must be false`)
    requireExact(value.formula_version, PAGE_WINDOW_FORMULA, `${field}.formula_version`)
    return {
      window: value.window as typeof PAGE_WINDOWS[number],
      cumulative_return_pct: decimal(value.cumulative_return_pct, `${field}.cumulative_return_pct`),
      max_drawdown_pct: decimal(value.max_drawdown_pct, `${field}.max_drawdown_pct`),
      trade_count: nonNegativeInteger(value.trade_count, `${field}.trade_count`),
      win_rate_pct: boundedDecimal(value.win_rate_pct, `${field}.win_rate_pct`, 0, 100),
      score: decimal(value.score, `${field}.score`),
      terminal_position_was_open: value.terminal_position_was_open,
      force_closed_at_end: true as const,
      execution_timing: 'same_bar_close' as const,
      trustworthy_for_research: false as const,
      formula_version: PAGE_WINDOW_FORMULA as typeof PAGE_WINDOW_FORMULA,
    }
  })
  const windows = items.map((item) => item.window)
  if (items.length !== PAGE_WINDOWS.length || new Set(windows).size !== PAGE_WINDOWS.length || PAGE_WINDOWS.some((window) => !windows.includes(window))) {
    throw new Error('page_window_comparison must contain the exact five page windows')
  }
  return items
}

function normalizeComposite(payload: unknown, field: string, page: true): NewowCompositeDecision
function normalizeComposite(payload: unknown, field: string, page: false): NewowCleanroomCompositeDecision
function normalizeComposite(
  payload: unknown,
  field: string,
  page: boolean,
): NewowCompositeDecision | NewowCleanroomCompositeDecision {
  const keys = [
    'trend_bias', 'oscillation_bias', 'direction_token', 'decision_key', 'action_token',
    'position_range', 'certainty', 'volatility', 'risk_tokens',
    ...(page ? ['unreachable_decision_keys'] : ['page_difference_reason']),
    'formula_version',
  ] as const
  const value = exactRecord(payload, field, keys)
  const trendBias = literal(value.trend_bias, TREND_BIASES, `${field}.trend_bias`)
  const oscillationBias = literal(value.oscillation_bias, OSCILLATION_BIASES, `${field}.oscillation_bias`)
  const decisionKey = literal(value.decision_key, DECISION_KEYS, `${field}.decision_key`)
  if (decisionKey !== `${trendBias}-${oscillationBias}`) throw new Error(`${field}.decision_key contradicts its biases`)
  const rangeValue = exactRecord(value.position_range, `${field}.position_range`, ['minimum', 'maximum'])
  const minimum = nullableDecimal(rangeValue.minimum, `${field}.position_range.minimum`)
  const maximum = nullableDecimal(rangeValue.maximum, `${field}.position_range.maximum`)
  if ((minimum === null) !== (maximum === null) || (minimum !== null && (minimum < 0 || maximum! > 1 || minimum > maximum!))) {
    throw new Error(`${field}.position_range is invalid`)
  }
  const certaintyValue = exactRecord(value.certainty, `${field}.certainty`, ['trend', 'oscillation', 'alignment', 'direction', 'total'])
  const certainty = {
    trend: nonNegativeInteger(certaintyValue.trend, `${field}.certainty.trend`),
    oscillation: nonNegativeInteger(certaintyValue.oscillation, `${field}.certainty.oscillation`),
    alignment: nonNegativeInteger(certaintyValue.alignment, `${field}.certainty.alignment`),
    direction: nonNegativeInteger(certaintyValue.direction, `${field}.certainty.direction`),
    total: nonNegativeInteger(certaintyValue.total, `${field}.certainty.total`),
  }
  if (certainty.total !== certainty.trend + certainty.oscillation + certainty.alignment + certainty.direction) {
    throw new Error(`${field}.certainty.total contradicts its components`)
  }
  const volatilityValue = exactRecord(value.volatility, `${field}.volatility`, ['value_pct', 'level', 'sample_size'])
  const common = {
    trend_bias: trendBias,
    oscillation_bias: oscillationBias,
    direction_token: literal(value.direction_token, DIRECTION_TOKENS, `${field}.direction_token`),
    decision_key: decisionKey,
    action_token: literal(value.action_token, ACTION_TOKENS, `${field}.action_token`),
    position_range: { minimum, maximum },
    certainty,
    volatility: {
      value_pct: decimal(volatilityValue.value_pct, `${field}.volatility.value_pct`),
      level: literal(volatilityValue.level, ['low', 'mid', 'high'] as const, `${field}.volatility.level`),
      sample_size: nonNegativeInteger(volatilityValue.sample_size, `${field}.volatility.sample_size`),
    },
    risk_tokens: stringArray(value.risk_tokens, `${field}.risk_tokens`, true),
  }
  if (page) {
    requireExact(value.formula_version, PAGE_COMPOSITE_FORMULA, `${field}.formula_version`)
    const unreachable = stringArray(value.unreachable_decision_keys, `${field}.unreachable_decision_keys`, true)
    if (unreachable.length !== UNREACHABLE_DECISION_KEYS.length || unreachable.some((item, index) => item !== UNREACHABLE_DECISION_KEYS[index])) {
      throw new Error(`${field}.unreachable_decision_keys must match the frozen page matrix`)
    }
    return { ...common, unreachable_decision_keys: unreachable, formula_version: PAGE_COMPOSITE_FORMULA }
  }
  requireExact(value.formula_version, CLEANROOM_COMPOSITE_FORMULA, `${field}.formula_version`)
  return {
    ...common,
    page_difference_reason: nullableText(value.page_difference_reason, `${field}.page_difference_reason`),
    formula_version: CLEANROOM_COMPOSITE_FORMULA,
  }
}

function normalizeFirstAction(payload: unknown): NewowTrendDetailResponse['first_action_principle'] {
  const value = exactRecord(payload, 'first_action_principle', ['level', 'rule_token', 'fact_tokens', 'formula_version'])
  requireExact(value.formula_version, FIRST_ACTION_FORMULA, 'first_action_principle.formula_version')
  return {
    level: literal(value.level, ['violate', 'warn', 'ok'] as const, 'first_action_principle.level'),
    rule_token: text(value.rule_token, 'first_action_principle.rule_token'),
    fact_tokens: stringArray(value.fact_tokens, 'first_action_principle.fact_tokens', true),
    formula_version: FIRST_ACTION_FORMULA,
  }
}

function normalizeDiagnosticFacts(
  payload: unknown,
  bars: readonly NewowBar[],
  channel: NewowPriceChannel,
): NewowTrendDetailResponse['diagnostic_facts'] {
  const value = exactRecord(payload, 'diagnostic_facts', [
    'as_of', 'target_price', 'absorb_price', 'target_distance_pct', 'absorb_distance_pct',
    'ema20', 'close_vs_ema20', 'trend_state', 'trend_duration_bars', 'oscillation_holding',
    'main_force_status', 'main_rise_active', 'cup_state', 'weekly_signal', 'daily_signal',
    'repainting_inputs_excluded', 'formula_versions',
  ])
  const asOf = instant(value.as_of, 'diagnostic_facts.as_of')
  if (bars.length > 0 && asOf !== bars.at(-1)!.bar_end) throw new Error('diagnostic_facts.as_of must equal the latest visible bar')
  const formulaVersions = stringArray(value.formula_versions, 'diagnostic_facts.formula_versions', true)
  if (formulaVersions.some((formula) => !FORMULA_VERSIONS.includes(formula as typeof FORMULA_VERSIONS[number]))) {
    throw new Error('diagnostic_facts.formula_versions contains unknown lineage')
  }
  const excluded = stringArray(value.repainting_inputs_excluded, 'diagnostic_facts.repainting_inputs_excluded', true)
  const oscillationHolding = value.oscillation_holding
  if (oscillationHolding !== null && typeof oscillationHolding !== 'boolean') throw new Error('diagnostic_facts.oscillation_holding must be boolean or null')
  const mainRiseActive = value.main_rise_active
  if (mainRiseActive !== null && typeof mainRiseActive !== 'boolean') throw new Error('diagnostic_facts.main_rise_active must be boolean or null')
  const targetPrice = nullableDecimal(value.target_price, 'diagnostic_facts.target_price')
  const absorbPrice = nullableDecimal(value.absorb_price, 'diagnostic_facts.absorb_price')
  if (targetPrice !== channel.display.target || absorbPrice !== channel.display.absorb) throw new Error('diagnostic channel prices disagree with display facts')
  return {
    as_of: asOf,
    target_price: targetPrice,
    absorb_price: absorbPrice,
    target_distance_pct: nullableDecimal(value.target_distance_pct, 'diagnostic_facts.target_distance_pct'),
    absorb_distance_pct: nullableDecimal(value.absorb_distance_pct, 'diagnostic_facts.absorb_distance_pct'),
    ema20: nullableDecimal(value.ema20, 'diagnostic_facts.ema20'),
    close_vs_ema20: literal(value.close_vs_ema20, ['above', 'below', 'equal', 'unavailable'] as const, 'diagnostic_facts.close_vs_ema20'),
    trend_state: literal(value.trend_state, TREND_STATES, 'diagnostic_facts.trend_state'),
    trend_duration_bars: nonNegativeInteger(value.trend_duration_bars, 'diagnostic_facts.trend_duration_bars'),
    oscillation_holding: oscillationHolding,
    main_force_status: value.main_force_status === null ? null : literal(value.main_force_status, ['无庄控盘', '开始控盘', '有庄控盘', '高度控盘', '主力出货', '高控+出货'] as const, 'diagnostic_facts.main_force_status'),
    main_rise_active: mainRiseActive,
    cup_state: value.cup_state === null ? null : literal(value.cup_state, ['NONE', ...CUP_STATES] as const, 'diagnostic_facts.cup_state'),
    weekly_signal: value.weekly_signal === null ? null : literal(value.weekly_signal, ['buy', 'hold', 'sell', 'wait'] as const, 'diagnostic_facts.weekly_signal'),
    daily_signal: value.daily_signal === null ? null : literal(value.daily_signal, ['buy', 'hold', 'sell', 'wait'] as const, 'diagnostic_facts.daily_signal'),
    repainting_inputs_excluded: excluded,
    formula_versions: formulaVersions,
  }
}

function normalizeDiagnosticTokens(payload: unknown): NewowTrendDetailResponse['diagnostic_tokens'][number][] {
  const tokens = array(payload, 'diagnostic_tokens').map((item, index) => {
    const field = `diagnostic_tokens[${index}]`
    const value = exactRecord(item, field, ['code', 'severity', 'fact_keys', 'formula_identities'])
    const formulas = stringArray(value.formula_identities, `${field}.formula_identities`, true)
    if (formulas.some((formula) => !FORMULA_VERSIONS.includes(formula as typeof FORMULA_VERSIONS[number]))) {
      throw new Error(`${field}.formula_identities contains unknown lineage`)
    }
    return {
      code: text(value.code, `${field}.code`),
      severity: literal(value.severity, ['info', 'warning', 'risk'] as const, `${field}.severity`),
      fact_keys: stringArray(value.fact_keys, `${field}.fact_keys`, true),
      formula_identities: formulas,
    }
  })
  if (new Set(tokens.map((token) => token.code)).size !== tokens.length) throw new Error('diagnostic_tokens.code must be unique')
  return tokens
}

function normalizeSemanticLabels(payload: unknown): NewowTrendDetailResponse['semantic_labels'] {
  const value = exactRecord(payload, 'semantic_labels', [
    'page_parity', 'cleanroom_separated', 'observation_only',
    'causal_research_result', 'repainting_input_used',
  ])
  if (value.page_parity !== true || value.cleanroom_separated !== true || value.observation_only !== true
    || value.causal_research_result !== false || value.repainting_input_used !== false) {
    throw new Error('semantic_labels must preserve the observation-only trust boundary')
  }
  return {
    page_parity: true, cleanroom_separated: true, observation_only: true,
    causal_research_result: false, repainting_input_used: false,
  }
}

function normalizeWarnings(
  payload: unknown,
  bars: readonly NewowBar[],
  points: readonly NewowTrendBandPoint[],
  compositeUnavailable: boolean,
): NewowWarning[] {
  const warnings = array(payload, 'warnings').map((item, index) => literal(item, WARNINGS, `warnings[${index}]`))
  if (new Set(warnings).size !== warnings.length) throw new Error('warnings must be unique')
  if (warnings.some((warning, index) => index > 0 && WARNINGS.indexOf(warning) <= WARNINGS.indexOf(warnings[index - 1]!))) {
    throw new Error('warnings must use canonical order')
  }
  if (bars.length === 0) {
    if (warnings.length !== WARNINGS.length) throw new Error('empty Newow results require all warmup warnings')
  } else {
    const trendUnavailable = points.at(-1)!.state === 'UNAVAILABLE'
    if (warnings.includes('NEWOW_TREND_WARMUP_INSUFFICIENT') !== trendUnavailable) {
      throw new Error('trend warmup warning contradicts the latest trend state')
    }
  }
  if (warnings.includes('NEWOW_COMPOSITE_DAILY_BARS_INSUFFICIENT') !== compositeUnavailable) {
    throw new Error('composite warning contradicts composite availability')
  }
  return warnings
}

function exactRecord<const K extends readonly string[]>(
  value: unknown,
  field: string,
  keys: K,
): Record<K[number], unknown> {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) {
    throw new Error(`${field} must be an object`)
  }
  const prototype = Object.getPrototypeOf(value)
  if (prototype !== Object.prototype && prototype !== null) throw new Error(`${field} must be a plain object`)
  const actual = Object.keys(value)
  const expected = new Set<string>(keys)
  const unknown = actual.filter((key) => !expected.has(key))
  const missing = keys.filter((key) => !Object.hasOwn(value, key))
  if (unknown.length > 0) throw new Error(`${field} has unexpected fields: ${unknown.join(', ')}`)
  if (missing.length > 0) throw new Error(`${field} is missing fields: ${missing.join(', ')}`)
  return value as Record<K[number], unknown>
}

function array(value: unknown, field: string): unknown[] {
  if (!Array.isArray(value)) throw new Error(`${field} must be an array`)
  return value
}

function text(value: unknown, field: string): string {
  if (typeof value !== 'string' || value.length === 0 || value.trim() !== value) {
    throw new Error(`${field} must be a non-empty trimmed string`)
  }
  return value
}

function nullableText(value: unknown, field: string): string | null {
  return value === null ? null : text(value, field)
}

function requireExact<T extends string>(value: unknown, expected: T, field: string): asserts value is T {
  if (value !== expected) throw new Error(`${field} must be ${expected}`)
}

function literal<const T extends readonly string[]>(value: unknown, accepted: T, field: string): T[number] {
  if (typeof value !== 'string' || !accepted.includes(value)) throw new Error(`${field} is invalid`)
  return value as T[number]
}

function day(value: unknown, field: string): string {
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value)) throw new Error(`${field} must be an ISO date`)
  const parsed = new Date(`${value}T00:00:00Z`)
  if (!Number.isFinite(parsed.getTime()) || parsed.toISOString().slice(0, 10) !== value) throw new Error(`${field} is invalid`)
  return value
}

function instant(value: unknown, field: string): string {
  if (typeof value !== 'string') throw new Error(`${field} must be an ISO instant with timezone`)
  const match = /^(\d{4}-\d{2}-\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d+)?(Z|([+-])(\d{2}):(\d{2}))$/.exec(value)
  if (match === null) throw new Error(`${field} must be an ISO instant with timezone`)
  day(match[1], field)
  const hour = Number(match[2])
  const minute = Number(match[3])
  const second = Number(match[4])
  const offsetHour = match[7] === undefined ? 0 : Number(match[7])
  const offsetMinute = match[8] === undefined ? 0 : Number(match[8])
  if (hour > 23 || minute > 59 || second > 59 || offsetHour > 14 || offsetMinute > 59 || (offsetHour === 14 && offsetMinute !== 0)) {
    throw new Error(`${field} must be an ISO instant with timezone`)
  }
  if (!Number.isFinite(Date.parse(value))) throw new Error(`${field} must be an ISO instant with timezone`)
  return value
}

function instantValue(value: string): number {
  return Date.parse(value)
}

function validateIncreasingInstants(values: readonly string[], field: string): void {
  for (let index = 1; index < values.length; index += 1) {
    if (instantValue(values[index]!) <= instantValue(values[index - 1]!)) {
      throw new Error(`${field} must be strictly ordered and unique`)
    }
  }
}

function positiveDecimal(value: unknown, field: string): number {
  const normalized = decimal(value, field)
  if (normalized <= 0) throw new Error(`${field} must be a finite positive Decimal string`)
  return normalized
}

function decimal(value: unknown, field: string): number {
  if (typeof value !== 'string' || !DECIMAL_PATTERN.test(value)) {
    throw new Error(`${field} must be a Decimal string`)
  }
  const normalized = Number(value)
  if (!Number.isFinite(normalized)) throw new Error(`${field} must be a finite Decimal string`)
  if (canonicalDecimal(value) !== canonicalDecimal(String(normalized))) {
    throw new Error(`${field} exceeds safe chart-number precision`)
  }
  return normalized
}

function nullableDecimal(value: unknown, field: string): number | null {
  return value === null ? null : decimal(value, field)
}

function boundedDecimal(value: unknown, field: string, minimum: number, maximum: number): number {
  const normalized = decimal(value, field)
  if (normalized < minimum || normalized > maximum) throw new Error(`${field} must be between ${minimum} and ${maximum}`)
  return normalized
}

function canonicalDecimal(value: string): string {
  const match = DECIMAL_PATTERN.exec(value)
  if (match === null) throw new Error('invalid Decimal string')
  const negative = match[1] === '-'
  const integerDigits = match[2] ?? ''
  const fractionalDigits = match[2] === undefined ? (match[4] ?? '') : (match[3] ?? '')
  let coefficient = `${integerDigits}${fractionalDigits}`.replace(/^0+/, '')
  if (coefficient.length === 0) return '0e0'
  let exponent = BigInt(match[5] ?? '0') - BigInt(fractionalDigits.length)
  while (coefficient.endsWith('0')) {
    coefficient = coefficient.slice(0, -1)
    exponent += 1n
  }
  return `${negative ? '-' : ''}${coefficient}e${exponent}`
}

function nullableFinite(value: unknown, field: string): number | null {
  if (value === null) return null
  if (typeof value !== 'number' || !Number.isFinite(value)) throw new Error(`${field} must be finite or null`)
  return value
}

function boundedNumber(value: unknown, field: string, minimum: number, maximum: number): number {
  if (typeof value !== 'number' || !Number.isFinite(value) || value < minimum || value > maximum) {
    throw new Error(`${field} must be finite and between ${minimum} and ${maximum}`)
  }
  return value
}

function nonNegativeInteger(value: unknown, field: string): number {
  if (typeof value !== 'number' || !Number.isSafeInteger(value) || value < 0) {
    throw new Error(`${field} must be a non-negative safe integer`)
  }
  return value
}

function contract(value: unknown, field: string): string {
  const normalized = text(value, field)
  if (!/^[A-Z]+[0-9]+$/.test(normalized)) throw new Error(`${field} must be an uppercase physical contract`)
  return normalized
}

function nullableContract(value: unknown, field: string): string | null {
  return value === null ? null : contract(value, field)
}

function stringArray(value: unknown, field: string, requireUnique: boolean): string[] {
  const normalized = array(value, field).map((item, index) => text(item, `${field}[${index}]`))
  if (requireUnique && new Set(normalized).size !== normalized.length) throw new Error(`${field} must be unique`)
  return normalized
}

function finiteMap<const K extends readonly string[]>(value: unknown, field: string, keys: K): Record<K[number], number> {
  const mapped = exactRecord(value, field, keys)
  return Object.fromEntries(keys.map((key) => [key, finiteNumber(mapped[key as K[number]], `${field}.${key}`)])) as Record<K[number], number>
}

function finiteNumber(value: unknown, field: string): number {
  if (typeof value !== 'number' || !Number.isFinite(value)) throw new Error(`${field} must be finite`)
  return value
}

function jsonRecord(value: unknown, field: string): Readonly<Record<string, NewowJsonValue>> {
  const normalized = jsonValue(value, field, new Set<object>())
  if (normalized === null || typeof normalized !== 'object' || Array.isArray(normalized)) {
    throw new Error(`${field} must be a JSON object`)
  }
  return normalized as Readonly<Record<string, NewowJsonValue>>
}

function jsonValue(value: unknown, field: string, ancestors: Set<object>): NewowJsonValue {
  if (value === null || typeof value === 'string' || typeof value === 'boolean') return value
  if (typeof value === 'number') {
    if (!Number.isFinite(value)) throw new Error(`${field} contains a non-finite number`)
    return value
  }
  if (typeof value !== 'object') throw new Error(`${field} contains a non-JSON value`)
  if (ancestors.has(value)) throw new Error(`${field} contains a cycle`)
  ancestors.add(value)
  try {
    if (Array.isArray(value)) {
      return value.map((item, index) => jsonValue(item, `${field}[${index}]`, ancestors))
    }
    const prototype = Object.getPrototypeOf(value)
    if (prototype !== Object.prototype && prototype !== null) throw new Error(`${field} contains a non-plain object`)
    return Object.fromEntries(
      Object.entries(value).map(([key, item]) => [key, jsonValue(item, `${field}.${key}`, ancestors)]),
    )
  } finally {
    ancestors.delete(value)
  }
}

function deepFreeze<T>(value: T): T {
  if (value !== null && typeof value === 'object' && !Object.isFrozen(value)) {
    for (const nested of Object.values(value as Record<string, unknown>)) deepFreeze(nested)
    Object.freeze(value)
  }
  return value
}
