import type {
  NewowAuxiliaryValue,
  NewowChartValue,
  NewowComparatorDisplay,
  NewowComparatorProductValue,
  NewowComparatorResult,
  NewowComparatorSegment,
  NewowComparatorSourceBars,
  NewowComparatorTrade,
  NewowComparatorValue,
  NewowCompositeDecision,
  NewowCompositeDirection,
  NewowCompositeInputFact,
  NewowCompositeResult,
  NewowCompositeValue,
  NewowCompositeVolatility,
  NewowContextSlot,
  NewowContextSnapshot,
  NewowCupPivotValue,
  NewowCupWitness,
  NewowCertaintyBreakdown,
  NewowEvidenceStatus,
  NewowExplanationValue,
  NewowFeatureStatus,
  NewowFirstAction,
  NewowMainForceControlData,
  NewowPageFact,
  NewowProductAction,
  NewowProductBar,
  NewowProductFrame,
  NewowProductHint,
  NewowProductIdentity,
  NewowProductMeta,
  NewowProductRequest,
  NewowProductSection,
  NewowProductSectionResponse,
  NewowProductStrategy,
  NewowReferenceSummary,
  NewowReferenceTrade,
  NewowReferenceValue,
  NewowRuntimeStatus,
  NewowSourceBars,
  NewowSourceFact,
  NewowSubfeature,
  NewowTargetAbsorbResult,
  NewowTargetAbsorbValue,
  NewowTargetDisplayPrice,
  NewowUpDownEnergyData,
  NewowWeekDayMatrix,
  NewowWindowComparison,
  NewowZhaoyaoMirrorData,
} from '../types/newowProduct.ts'

const SECTIONS = ['chart', 'auxiliary', 'reference', 'explanation', 'comparator'] as const
const STRATEGIES = ['trend', 'oscillation', 'main_rise'] as const
const FREQUENCIES = ['1w', '1d', '60m'] as const
const RUNTIME_STATUSES = ['ready', 'warming', 'unavailable', 'not_applicable', 'evidence_required'] as const
const EVIDENCE_STATUSES = ['ACTIVE_CODE_VERIFIED', 'RESEARCH_EVIDENCE_ONLY', 'EVIDENCE_REQUIRED', 'OUT_OF_SCOPE'] as const
const EXPECTED_FORMULAS: Record<NewowProductStrategy, readonly string[]> = {
  trend: ['newow_escape_d123_page_v2', 'newow_trend_band_page_v2'],
  oscillation: ['newow_hhv_llv_channel_page_v1', 'newow_oscillation_hhv_llv10_page_v1'],
  main_rise: ['newow_buy_d456_page_v1', 'newow_escape_d123_page_v2', 'newow_magic11_page_v1', 'newow_main_rise_j_reduce_page_v1', 'newow_main_rise_ma35_ma45_page_v1'],
}
const DECIMAL = /^[+-]?(?:(?:0|[1-9]\d*)(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$/
const HASH = /^[0-9a-f]{64}$/

type FlatExpected = NewowProductIdentity & { readonly section: NewowProductSection; readonly asOf: string }
type NormalizedExpected = FlatExpected & {
  readonly component?: NewowAuxiliaryValue['component']
  readonly performanceSince?: string
  readonly performanceThrough?: string
}

export function normalizeNewowProductResponse(
  payload: unknown,
  expectedRequest: NewowProductRequest | FlatExpected,
): NewowProductSectionResponse {
  const expected = normalizeExpected(expectedRequest)
  const top = exactRecord(payload, 'Newow product response', ['meta', 'section', 'chart', 'auxiliary', 'reference', 'explanation', 'comparator'])
  const section = literal(top.section, SECTIONS, 'section')
  if (section !== expected.section) throw new Error('section disagrees with the requested section')
  const meta = normalizeMeta(top.meta, expected)
  let requestedStatus: NewowFeatureStatus | null = null
  let requestedValue: unknown = null
  for (const candidate of SECTIONS) {
    const delivery = exactRecord(top[candidate], candidate, ['delivery', 'status', 'value'])
    if (candidate !== section) {
      if (delivery.delivery !== 'not_requested' || delivery.status !== null || delivery.value !== null) {
        throw new Error(`${candidate} not_requested wrapper must have null status and value`)
      }
      continue
    }
    if (delivery.delivery !== 'delivered') throw new Error(`${candidate} must be delivered`)
    requestedStatus = normalizeStatus(delivery.status, `${candidate}.status`)
    requestedValue = delivery.value
  }
  if (requestedStatus === null) throw new Error('requested section status is missing')
  if (requestedStatus.status === 'ready' && requestedValue === null) throw new Error('ready requested section must have a value')

  const value = requestedValue === null ? null : normalizeSectionValue(section, requestedValue, meta, expected)
  return deepFreeze({ meta, section, status: requestedStatus, value } as NewowProductSectionResponse)
}

export function chartCoordinate(value: string): number {
  decimal(value, 'chart coordinate')
  const coordinate = Number(value)
  if (!Number.isFinite(coordinate)) throw new Error('Decimal is outside the finite chart coordinate range')
  return coordinate
}

export function sharedChartBarsAgree(
  left: NewowProductSectionResponse,
  right: NewowProductSectionResponse,
): boolean {
  if (left.section !== 'chart' || right.section !== 'chart' || left.value === null || right.value === null) return true
  const leftBars = new Map(left.value.bars.map((bar) => [bar.bar_end, bar]))
  for (const bar of right.value.bars) {
    const other = leftBars.get(bar.bar_end)
    if (other !== undefined && chartBarFingerprint(other) !== chartBarFingerprint(bar)) return false
  }
  return true
}

function chartBarFingerprint(bar: NewowProductBar): string {
  return JSON.stringify([
    bar.bar_end, bar.trading_day, bar.open, bar.high, bar.low, bar.close, bar.volume,
    bar.open_interest, bar.physical_contract, bar.segment_id, bar.source_identity,
    bar.observation_eligible, bar.completed,
  ])
}

function normalizeExpected(request: NewowProductRequest | FlatExpected): NormalizedExpected {
  if ('identity' in request) {
    const common = { ...request.identity, section: request.section, asOf: request.asOf }
    if (request.section === 'auxiliary') return { ...common, component: request.component }
    if (request.section === 'reference') return { ...common, performanceSince: request.performanceSince, performanceThrough: request.performanceThrough }
    return common
  }
  return request
}

function normalizeMeta(payload: unknown, expected: FlatExpected): NewowProductMeta {
  const value = exactRecord(payload, 'meta', [
    'schema_version', 'identity', 'as_of', 'read_at', 'input_content_sha256', 'data_revision_identity',
    'snapshot_token', 'reference_model_version', 'futures_adaptation_version',
  ])
  requireExact(value.schema_version, 'newow_product_detail_v1', 'meta.schema_version')
  const normalizedIdentity = normalizeWireIdentity(value.identity, 'meta.identity', expected)
  requireExact(expected.seriesKind, 'actual_dominant', 'expected.seriesKind')
  const asOf = instant(value.as_of, 'meta.as_of')
  if (Date.parse(asOf) !== Date.parse(instant(expected.asOf, 'expected.asOf'))) throw new Error('meta.as_of disagrees with the fixed generation as_of')
  const readAt = instant(value.read_at, 'meta.read_at')
  const inputHash = sha256(value.input_content_sha256, 'meta.input_content_sha256')
  const revision = nullableText(value.data_revision_identity, 'meta.data_revision_identity')
  const token = nullableText(value.snapshot_token, 'meta.snapshot_token')
  requireExact(value.reference_model_version, 'newow_marker_reference_zero_cost_v1', 'meta.reference_model_version')
  requireExact(value.futures_adaptation_version, 'newow_futures_segment_interrupt_v1', 'meta.futures_adaptation_version')
  return {
    schema_version: 'newow_product_detail_v1',
    identity: normalizedIdentity,
    as_of: asOf, read_at: readAt, input_content_sha256: inputHash, data_revision_identity: revision,
    snapshot_token: token, reference_model_version: 'newow_marker_reference_zero_cost_v1',
    futures_adaptation_version: 'newow_futures_segment_interrupt_v1',
  }
}

function normalizeWireIdentity(
  payload: unknown,
  field: string,
  expected: Pick<NewowProductIdentity, 'product' | 'strategy' | 'frequency'>,
): NewowProductMeta['identity'] {
  const value = exactRecord(payload, field, ['product', 'strategy', 'frequency', 'series_kind', 'profile_id', 'formula_versions'])
  const product = productCode(value.product, `${field}.product`)
  const strategy = literal(value.strategy, STRATEGIES, `${field}.strategy`)
  const frequency = literal(value.frequency, FREQUENCIES, `${field}.frequency`)
  requireExact(product, expected.product, `${field}.product`)
  requireExact(strategy, expected.strategy, `${field}.strategy`)
  requireExact(frequency, expected.frequency, `${field}.frequency`)
  requireExact(value.series_kind, 'actual_dominant', `${field}.series_kind`)
  const profileId = text(value.profile_id, `${field}.profile_id`)
  requireExact(profileId, `newow_product_${strategy}_${frequency}_v1`, `${field}.profile_id`)
  const formulaVersions = stringArray(value.formula_versions, `${field}.formula_versions`)
  if (!sameStrings(formulaVersions, EXPECTED_FORMULAS[strategy])) throw new Error(`${field}.formula_versions is invalid or out of order`)
  return { product, strategy, frequency, series_kind: 'actual_dominant', profile_id: profileId, formula_versions: formulaVersions }
}

function normalizeStatus(payload: unknown, field: string): NewowFeatureStatus {
  const value = exactRecord(payload, field, ['status', 'evidence_status', 'reason_code'])
  const status = literal(value.status, RUNTIME_STATUSES, `${field}.status`) as NewowRuntimeStatus
  const evidence = literal(value.evidence_status, EVIDENCE_STATUSES, `${field}.evidence_status`) as NewowEvidenceStatus
  const reason = nullableText(value.reason_code, `${field}.reason_code`)
  if ((status === 'ready') === (reason !== null)) throw new Error(`${field}.reason_code contradicts status`)
  return { status, evidence_status: evidence, reason_code: reason }
}

function normalizeSectionValue(section: NewowProductSection, payload: unknown, meta: NewowProductMeta, expected: NormalizedExpected) {
  if (section === 'chart') return normalizeChart(payload)
  if (section === 'reference') return normalizeReference(payload, meta, expected)
  if (section === 'auxiliary') return normalizeAuxiliary(payload, expected.component)
  if (section === 'explanation') return normalizeExplanation(payload, meta)
  return normalizeComparator(payload, meta)
}

function normalizeChart(payload: unknown): NewowChartValue {
  const value = exactRecord(payload, 'chart.value', [
    'chart_from', 'chart_through', 'page_identity', 'bars', 'frames', 'actions', 'hints',
    'diagnostics', 'next_before', 'repainting', 'formal_signal_eligible', 'allowed_uses',
  ])
  const chartFrom = day(value.chart_from, 'chart_from')
  const chartThrough = day(value.chart_through, 'chart_through')
  if (chartFrom > chartThrough) throw new Error('chart window is invalid')
  const bars = array(value.bars, 'bars').map(normalizeBar)
  requireOrderedUnique(bars, (bar) => bar.bar_end, 'bars')
  const barEnds = new Set(bars.map((bar) => bar.bar_end))
  const frames = array(value.frames, 'frames').map((frame, index) => normalizeFrame(frame, index, barEnds))
  requireOrderedUnique(frames, (frame) => frame.bar_end, 'frames')
  const actions = array(value.actions, 'actions').map((action, index) => normalizeAction(action, index, barEnds))
  requireSequenceOrder(actions, 'actions')
  const hints = array(value.hints, 'hints').map((hint, index) => normalizeHint(hint, index, barEnds))
  requireTimelineOrder(hints, 'hints')
  validateChartRelationships(bars, frames, actions, hints)
  requireExact(value.repainting, false, 'chart.repainting')
  requireExact(value.formal_signal_eligible, true, 'chart.formal_signal_eligible')
  const allowed = exactStringArray(value.allowed_uses, ['product_chart', 'reference_input'] as const, 'chart.allowed_uses')
  return {
    chart_from: chartFrom, chart_through: chartThrough, page_identity: sha256(value.page_identity, 'chart.page_identity'),
    bars, frames, actions, hints, diagnostics: stringArray(value.diagnostics, 'chart.diagnostics'),
    next_before: nullableText(value.next_before, 'chart.next_before'), repainting: false,
    formal_signal_eligible: true, allowed_uses: allowed,
  }
}

function validateChartRelationships(
  bars: readonly NewowProductBar[],
  frames: readonly NewowProductFrame[],
  actions: readonly NewowProductAction[],
  hints: readonly NewowProductHint[],
): void {
  const barByEnd = new Map(bars.map((bar) => [bar.bar_end, bar]))
  for (const action of actions) {
    const bar = barByEnd.get(action.bar_end)!
    if (action.physical_contract !== bar.physical_contract || action.segment_id !== bar.segment_id) throw new Error('actions owner conflicts with its Bar')
    if (action.trading_day !== bar.trading_day) throw new Error('actions trading_day conflicts with its Bar')
  }
  for (const hint of hints) {
    const bar = barByEnd.get(hint.bar_end)!
    if (hint.physical_contract !== bar.physical_contract || hint.segment_id !== bar.segment_id) throw new Error('hints owner conflicts with its Bar')
  }
  if (frames.length !== bars.length || frames.some((frame, index) => frame.bar_end !== bars[index]!.bar_end)) throw new Error('frames must align exactly with bars')
  for (const frame of frames) {
    const expectedActions = actions.filter((action) => action.bar_end === frame.bar_end).map((action) => action.signal_id)
    const expectedHints = hints.filter((hint) => hint.bar_end === frame.bar_end).map((hint) => hint.hint_id)
    if (!sameStrings(frame.action_ids, expectedActions)) throw new Error('frame.action_ids conflict with chart actions')
    if (!sameStrings(frame.hint_ids, expectedHints)) throw new Error('frame.hint_ids conflict with chart hints')
  }
}

function normalizeBar(payload: unknown, index: number): NewowProductBar {
  const field = `bars[${index}]`
  const value = exactRecord(payload, field, [
    'bar_end', 'trading_day', 'open', 'high', 'low', 'close', 'volume', 'open_interest',
    'physical_contract', 'segment_id', 'source_identity', 'observation_eligible', 'completed',
  ])
  const open = decimal(value.open, `${field}.open`)
  const high = decimal(value.high, `${field}.high`)
  const low = decimal(value.low, `${field}.low`)
  const close = decimal(value.close, `${field}.close`)
  if (compareDecimal(low, high) > 0 || compareDecimal(open, low) < 0 || compareDecimal(open, high) > 0 || compareDecimal(close, low) < 0 || compareDecimal(close, high) > 0) {
    throw new Error(`${field} has invalid OHLC order`)
  }
  requireExact(value.completed, true, `${field}.completed`)
  return {
    bar_end: instant(value.bar_end, `${field}.bar_end`), trading_day: day(value.trading_day, `${field}.trading_day`),
    open, high, low, close, volume: count(value.volume, `${field}.volume`),
    open_interest: value.open_interest === null ? null : count(value.open_interest, `${field}.open_interest`),
    physical_contract: contract(value.physical_contract, `${field}.physical_contract`),
    segment_id: text(value.segment_id, `${field}.segment_id`), source_identity: text(value.source_identity, `${field}.source_identity`),
    observation_eligible: boolean(value.observation_eligible, `${field}.observation_eligible`), completed: true,
  }
}

function normalizeFrame(payload: unknown, index: number, barEnds: Set<string>): NewowProductFrame {
  const field = `frames[${index}]`
  const value = exactRecord(payload, field, ['bar_end', 'main_state', 'main_values', 'status', 'action_ids', 'hint_ids'])
  const barEnd = instant(value.bar_end, `${field}.bar_end`)
  if (!barEnds.has(barEnd)) throw new Error(`${field} does not reference a chart bar`)
  const rawValues = record(value.main_values, `${field}.main_values`)
  const mainValues: Record<string, string | null> = {}
  for (const [key, item] of Object.entries(rawValues)) mainValues[text(key, `${field}.main_values key`)] = item === null ? null : decimal(item, `${field}.main_values.${key}`)
  return {
    bar_end: barEnd, main_state: literal(value.main_state, ['BUILD', 'HOLD', 'CLEAR', 'FLAT', 'UNAVAILABLE'], `${field}.main_state`),
    main_values: mainValues, status: normalizeStatus(value.status, `${field}.status`),
    action_ids: uniqueStrings(value.action_ids, `${field}.action_ids`), hint_ids: uniqueStrings(value.hint_ids, `${field}.hint_ids`),
  }
}

function normalizeAction(payload: unknown, index: number, barEnds: Set<string>): NewowProductAction {
  const field = `actions[${index}]`
  const value = exactRecord(payload, field, ['signal_id', 'kind', 'bar_end', 'trading_day', 'reference_price', 'physical_contract', 'segment_id', 'related_build_id', 'trade_eligibility', 'sequence'])
  const barEnd = instant(value.bar_end, `${field}.bar_end`)
  if (!barEnds.has(barEnd)) throw new Error(`${field} does not reference a chart bar`)
  return {
    signal_id: text(value.signal_id, `${field}.signal_id`), kind: literal(value.kind, ['BUILD', 'CLEAR'], `${field}.kind`),
    bar_end: barEnd, trading_day: day(value.trading_day, `${field}.trading_day`), reference_price: decimal(value.reference_price, `${field}.reference_price`),
    physical_contract: contract(value.physical_contract, `${field}.physical_contract`), segment_id: text(value.segment_id, `${field}.segment_id`),
    related_build_id: nullableText(value.related_build_id, `${field}.related_build_id`),
    trade_eligibility: literal(value.trade_eligibility, ['ELIGIBLE', 'WARMUP_ONLY', 'NO_ELIGIBLE_ENTRY'], `${field}.trade_eligibility`),
    sequence: count(value.sequence, `${field}.sequence`),
  }
}

function normalizeHint(payload: unknown, index: number, barEnds: Set<string>): NewowProductHint {
  const field = `hints[${index}]`
  const value = exactRecord(payload, field, ['hint_id', 'kind', 'bar_end', 'known_at', 'anchor_price', 'physical_contract', 'segment_id', 'retrospective', 'quantity_effect', 'sequence'])
  const barEnd = instant(value.bar_end, `${field}.bar_end`)
  if (!barEnds.has(barEnd)) throw new Error(`${field} does not reference a chart bar`)
  requireExact(value.retrospective, false, `${field}.retrospective`)
  requireExact(value.quantity_effect, 'none', `${field}.quantity_effect`)
  return {
    hint_id: text(value.hint_id, `${field}.hint_id`), kind: text(value.kind, `${field}.kind`), bar_end: barEnd,
    known_at: instant(value.known_at, `${field}.known_at`), anchor_price: value.anchor_price === null ? null : decimal(value.anchor_price, `${field}.anchor_price`),
    physical_contract: contract(value.physical_contract, `${field}.physical_contract`), segment_id: text(value.segment_id, `${field}.segment_id`),
    retrospective: false, quantity_effect: 'none', sequence: value.sequence === null ? null : count(value.sequence, `${field}.sequence`),
  }
}

function normalizeReference(payload: unknown, meta: NewowProductMeta, expected: NormalizedExpected): NewowReferenceValue {
  const value = exactRecord(payload, 'reference.value', [
    'performance_since', 'performance_through', 'actual_available_through', 'reference_cutoff', 'reference_input_sha256',
    'summary', 'items', 'next_before', 'executable', 'auto_order', 'allowed_uses',
  ])
  const performanceSince = day(value.performance_since, 'reference.performance_since')
  const performanceThrough = day(value.performance_through, 'reference.performance_through')
  if (performanceSince > performanceThrough) throw new Error('reference performance window is invalid')
  if (expected.performanceSince !== undefined) requireExact(performanceSince, day(expected.performanceSince, 'expected.performance_since'), 'reference.performance_since')
  if (expected.performanceThrough !== undefined) requireExact(performanceThrough, day(expected.performanceThrough, 'expected.performance_through'), 'reference.performance_through')
  const summary = normalizeSummary(value.summary)
  const items = array(value.items, 'reference.items').map((item, index) => normalizeTrade(item, index, meta))
  requireReferenceOrder(items)
  if (new Set(items.map((item) => item.reference_trade_id)).size !== items.length) throw new Error('reference.items contains duplicate IDs')
  requireExact(value.executable, false, 'reference.executable')
  requireExact(value.auto_order, false, 'reference.auto_order')
  return {
    performance_since: performanceSince, performance_through: performanceThrough,
    actual_available_through: day(value.actual_available_through, 'reference.actual_available_through'),
    reference_cutoff: instant(value.reference_cutoff, 'reference.reference_cutoff'),
    reference_input_sha256: sha256(value.reference_input_sha256, 'reference.reference_input_sha256'),
    summary, items, next_before: nullableText(value.next_before, 'reference.next_before'), executable: false, auto_order: false,
    allowed_uses: exactStringArray(value.allowed_uses, ['page_parity_reference', 'research_display'] as const, 'reference.allowed_uses'),
  }
}

function normalizeSummary(payload: unknown): NewowReferenceSummary {
  const value = exactRecord(payload, 'reference.summary', [
    'membership_policy', 'closed_count', 'win_count', 'loss_count', 'flat_count', 'win_rate_pct',
    'mean_return_pct', 'sum_return_percentage_points', 'open_count', 'interrupted_count', 'initial_count',
  ])
  const result = {
    membership_policy: text(value.membership_policy, 'summary.membership_policy'),
    closed_count: count(value.closed_count, 'summary.closed_count'), win_count: count(value.win_count, 'summary.win_count'),
    loss_count: count(value.loss_count, 'summary.loss_count'), flat_count: count(value.flat_count, 'summary.flat_count'),
    win_rate_pct: nullableDecimal(value.win_rate_pct, 'summary.win_rate_pct'), mean_return_pct: nullableDecimal(value.mean_return_pct, 'summary.mean_return_pct'),
    sum_return_percentage_points: nullableDecimal(value.sum_return_percentage_points, 'summary.sum_return_percentage_points'),
    open_count: count(value.open_count, 'summary.open_count'), interrupted_count: count(value.interrupted_count, 'summary.interrupted_count'),
    initial_count: count(value.initial_count, 'summary.initial_count'),
  }
  if (result.closed_count !== result.win_count + result.loss_count + result.flat_count) throw new Error('reference summary CLOSED counts conflict')
  if (result.closed_count === 0 && (result.win_rate_pct !== null || result.mean_return_pct !== null || result.sum_return_percentage_points !== null)) {
    throw new Error('zero CLOSED summary must keep performance metrics null')
  }
  return result
}

function normalizeTrade(payload: unknown, index: number, meta: NewowProductMeta): NewowReferenceTrade {
  const field = `reference.items[${index}]`
  const value = exactRecord(payload, field, [
    'reference_trade_id', 'product', 'strategy_code', 'frequency', 'physical_contract', 'segment_id', 'formula_versions',
    'reference_model_version', 'futures_adaptation_version', 'entry_signal_id', 'entry_sequence', 'entry_bar_end', 'entry_trading_day',
    'entry_reference_price', 'exit_signal_id', 'exit_bar_end', 'exit_trading_day', 'exit_reference_price', 'status', 'holding_bars',
    'reference_return_pct', 'mark_bar_end', 'mark_reference_price', 'mark_change_pct', 'interrupted_at', 'interruption_reason',
    'statistics_membership', 'hint_ids',
  ])
  requireExact(value.product, meta.identity.product, `${field}.product`)
  requireExact(value.strategy_code, meta.identity.strategy, `${field}.strategy_code`)
  requireExact(value.frequency, meta.identity.frequency, `${field}.frequency`)
  if (!sameStrings(stringArray(value.formula_versions, `${field}.formula_versions`), meta.identity.formula_versions)) throw new Error(`${field}.formula_versions conflict`)
  requireExact(value.reference_model_version, meta.reference_model_version, `${field}.reference_model_version`)
  requireExact(value.futures_adaptation_version, meta.futures_adaptation_version, `${field}.futures_adaptation_version`)
  const status = literal(value.status, ['OPEN', 'CLOSED', 'ROLLOVER_INTERRUPTED'], `${field}.status`)
  const exitSignal = nullableText(value.exit_signal_id, `${field}.exit_signal_id`)
  const exitBar = nullableInstant(value.exit_bar_end, `${field}.exit_bar_end`)
  const exitDay = nullableDay(value.exit_trading_day, `${field}.exit_trading_day`)
  const exitPrice = nullableDecimal(value.exit_reference_price, `${field}.exit_reference_price`)
  const referenceReturn = nullableDecimal(value.reference_return_pct, `${field}.reference_return_pct`)
  if (status === 'CLOSED' && [exitSignal, exitBar, exitDay, exitPrice, referenceReturn].some((item) => item === null)) throw new Error(`${field} CLOSED facts are incomplete`)
  if (status !== 'CLOSED' && [exitSignal, exitBar, exitDay, exitPrice, referenceReturn].some((item) => item !== null)) throw new Error(`${field} non-CLOSED facts expose an exit`)
  return {
    reference_trade_id: text(value.reference_trade_id, `${field}.reference_trade_id`), product: meta.identity.product,
    strategy_code: meta.identity.strategy, frequency: meta.identity.frequency, physical_contract: contract(value.physical_contract, `${field}.physical_contract`),
    segment_id: text(value.segment_id, `${field}.segment_id`), formula_versions: meta.identity.formula_versions,
    reference_model_version: meta.reference_model_version, futures_adaptation_version: meta.futures_adaptation_version,
    entry_signal_id: text(value.entry_signal_id, `${field}.entry_signal_id`), entry_sequence: count(value.entry_sequence, `${field}.entry_sequence`),
    entry_bar_end: instant(value.entry_bar_end, `${field}.entry_bar_end`), entry_trading_day: day(value.entry_trading_day, `${field}.entry_trading_day`),
    entry_reference_price: decimal(value.entry_reference_price, `${field}.entry_reference_price`), exit_signal_id: exitSignal,
    exit_bar_end: exitBar, exit_trading_day: exitDay, exit_reference_price: exitPrice, status,
    holding_bars: count(value.holding_bars, `${field}.holding_bars`), reference_return_pct: referenceReturn,
    mark_bar_end: nullableInstant(value.mark_bar_end, `${field}.mark_bar_end`), mark_reference_price: nullableDecimal(value.mark_reference_price, `${field}.mark_reference_price`),
    mark_change_pct: nullableDecimal(value.mark_change_pct, `${field}.mark_change_pct`), interrupted_at: nullableInstant(value.interrupted_at, `${field}.interrupted_at`),
    interruption_reason: nullableText(value.interruption_reason, `${field}.interruption_reason`), statistics_membership: nullableText(value.statistics_membership, `${field}.statistics_membership`),
    hint_ids: uniqueStrings(value.hint_ids, `${field}.hint_ids`),
  }
}

function normalizeAuxiliary(payload: unknown, expectedComponent?: NewowAuxiliaryValue['component']): NewowAuxiliaryValue {
  const value = exactRecord(payload, 'auxiliary.value', ['component', 'formula_version', 'segments', 'repainting', 'formal_signal_eligible', 'page_parity', 'source_category', 'allowed_uses'])
  requireExact(value.source_category, 'guiyi_product_auxiliary_adapter', 'auxiliary.source_category')
  const component = literal(value.component, ['main_force_control', 'up_down_energy', 'zhaoyao_mirror', 'cup_handle'], 'auxiliary.component')
  if (expectedComponent !== undefined) requireExact(component, expectedComponent, 'auxiliary.component')
  const formulaVersion = text(value.formula_version, 'auxiliary.formula_version')
  const segments = array(value.segments, 'auxiliary.segments').map((segment, index) => {
    const field = `auxiliary.segments[${index}]`
    const item = exactRecord(segment, field, ['physical_contract', 'segment_id', 'bar_ends', 'status', 'data'])
    const barEnds = array(item.bar_ends, `${field}.bar_ends`).map((barEnd, barIndex) => instant(barEnd, `${field}.bar_ends[${barIndex}]`))
    requireOrderedUnique(barEnds, (barEnd) => barEnd, `${field}.bar_ends`)
    return {
      physical_contract: contract(item.physical_contract, `${field}.physical_contract`),
      segment_id: text(item.segment_id, `${field}.segment_id`),
      bar_ends: barEnds,
      status: normalizeStatus(item.status, `${field}.status`),
      data: item.data === null ? null : normalizeAuxiliaryData(item.data, component, formulaVersion, barEnds.length, `${field}.data`),
    }
  })
  return {
    component, formula_version: formulaVersion, segments,
    repainting: boolean(value.repainting, 'auxiliary.repainting'), formal_signal_eligible: boolean(value.formal_signal_eligible, 'auxiliary.formal_signal_eligible'),
    page_parity: boolean(value.page_parity, 'auxiliary.page_parity'), source_category: 'guiyi_product_auxiliary_adapter',
    allowed_uses: stringArray(value.allowed_uses, 'auxiliary.allowed_uses'),
  }
}

function normalizeAuxiliaryData(payload: unknown, component: NewowAuxiliaryValue['component'], formulaVersion: string, size: number, field: string) {
  if (component === 'cup_handle') {
    return array(payload, field).map((item, index) => normalizeCupWitness(item, `${field}[${index}]`, formulaVersion))
  }
  if (component === 'main_force_control') {
    const value = exactRecord(payload, field, ['kongpan', 'status', 'current_status', 'formula_version'])
    const result: NewowMainForceControlData = {
      kongpan: finiteArray(value.kongpan, `${field}.kongpan`), status: stringArray(value.status, `${field}.status`),
      current_status: text(value.current_status, `${field}.current_status`), formula_version: text(value.formula_version, `${field}.formula_version`),
    }
    requireAligned(size, field, result.kongpan, result.status)
    requireExact(result.formula_version, formulaVersion, `${field}.formula_version`)
    return result
  }
  if (component === 'zhaoyao_mirror') {
    const value = exactRecord(payload, field, ['entry', 'wash', 'distribution', 'markup', 'exit', 'inducement', 'peaks', 'caution', 'repainting', 'formal_signal_eligible', 'formula_version'])
    requireExact(value.repainting, true, `${field}.repainting`); requireExact(value.formal_signal_eligible, false, `${field}.formal_signal_eligible`)
    const result: NewowZhaoyaoMirrorData = {
      entry: finiteArray(value.entry, `${field}.entry`), wash: finiteArray(value.wash, `${field}.wash`),
      distribution: finiteArray(value.distribution, `${field}.distribution`), markup: finiteArray(value.markup, `${field}.markup`),
      exit: finiteArray(value.exit, `${field}.exit`), inducement: finiteArray(value.inducement, `${field}.inducement`),
      peaks: integerArray(value.peaks, `${field}.peaks`), caution: integerArray(value.caution, `${field}.caution`),
      repainting: true, formal_signal_eligible: false, formula_version: text(value.formula_version, `${field}.formula_version`),
    }
    requireAligned(size, field, result.entry, result.wash, result.distribution, result.markup, result.exit, result.inducement, result.peaks, result.caution)
    requireExact(result.formula_version, formulaVersion, `${field}.formula_version`)
    return result
  }
  const value = exactRecord(payload, field, ['var4', 'ma10', 'band_entry', 'rebound_entry', 'oversold_entry', 'var3', 'ma120', 'formula_version'])
  const result: NewowUpDownEnergyData = {
    var4: array(value.var4, `${field}.var4`).map((item, index) => item === null ? null : finiteNumber(item, `${field}.var4[${index}]`)),
    ma10: finiteArray(value.ma10, `${field}.ma10`), band_entry: integerArray(value.band_entry, `${field}.band_entry`),
    rebound_entry: integerArray(value.rebound_entry, `${field}.rebound_entry`), oversold_entry: integerArray(value.oversold_entry, `${field}.oversold_entry`),
    var3: finiteArray(value.var3, `${field}.var3`), ma120: finiteArray(value.ma120, `${field}.ma120`),
    formula_version: text(value.formula_version, `${field}.formula_version`),
  }
  requireAligned(size, field, result.var4, result.ma10, result.band_entry, result.rebound_entry, result.oversold_entry, result.var3, result.ma120)
  requireExact(result.formula_version, formulaVersion, `${field}.formula_version`)
  return result
}

function normalizeCupWitness(payload: unknown, field: string, formulaVersion: string): NewowCupWitness {
  const value = exactRecord(payload, field, ['witness_id', 'candidate_id', 'left_rim', 'bottom', 'right_rim', 'handle_extreme', 'pivot_price', 'confirmed_at', 'score', 'score_breakdown', 'volume_facts', 'right_leg_median_exact', 'handle_median_exact', 'handle_baseline_median_exact', 'profile_identity', 'formula_version'])
  const result: NewowCupWitness = {
    witness_id: text(value.witness_id, `${field}.witness_id`), candidate_id: text(value.candidate_id, `${field}.candidate_id`),
    left_rim: normalizeCupPivot(value.left_rim, `${field}.left_rim`), bottom: normalizeCupPivot(value.bottom, `${field}.bottom`),
    right_rim: normalizeCupPivot(value.right_rim, `${field}.right_rim`), handle_extreme: normalizeCupPivot(value.handle_extreme, `${field}.handle_extreme`),
    pivot_price: decimal(value.pivot_price, `${field}.pivot_price`), confirmed_at: instant(value.confirmed_at, `${field}.confirmed_at`),
    score: finiteNumber(value.score, `${field}.score`), score_breakdown: pairArray(value.score_breakdown, `${field}.score_breakdown`),
    volume_facts: pairArray(value.volume_facts, `${field}.volume_facts`), right_leg_median_exact: decimal(value.right_leg_median_exact, `${field}.right_leg_median_exact`),
    handle_median_exact: decimal(value.handle_median_exact, `${field}.handle_median_exact`), handle_baseline_median_exact: decimal(value.handle_baseline_median_exact, `${field}.handle_baseline_median_exact`),
    profile_identity: text(value.profile_identity, `${field}.profile_identity`), formula_version: text(value.formula_version, `${field}.formula_version`),
  }
  requireExact(result.formula_version, formulaVersion, `${field}.formula_version`)
  return result
}

function normalizeCupPivot(payload: unknown, field: string): NewowCupPivotValue {
  const value = exactRecord(payload, field, ['kind', 'price', 'pivot_at', 'confirmed_at', 'pivot_index', 'confirmed_index', 'atr_at_pivot'])
  return { kind: text(value.kind, `${field}.kind`), price: decimal(value.price, `${field}.price`), pivot_at: instant(value.pivot_at, `${field}.pivot_at`), confirmed_at: instant(value.confirmed_at, `${field}.confirmed_at`), pivot_index: count(value.pivot_index, `${field}.pivot_index`), confirmed_index: count(value.confirmed_index, `${field}.confirmed_index`), atr_at_pivot: finiteNumber(value.atr_at_pivot, `${field}.atr_at_pivot`) }
}

function normalizeExplanation(payload: unknown, meta: NewowProductMeta): NewowExplanationValue {
  const value = exactRecord(payload, 'explanation.value', ['context', 'composite', 'target_absorb', 'sources', 'page_parity', 'allowed_uses'])
  requireExact(value.page_parity, false, 'explanation.page_parity')
  return {
    context: normalizeContext(value.context, meta), composite: normalizeCompositeResult(value.composite, meta),
    target_absorb: normalizeTargetResult(value.target_absorb, meta),
    sources: array(value.sources, 'explanation.sources').map((source, index) => normalizeSourceFact(source, `explanation.sources[${index}]`, meta)), page_parity: false,
    allowed_uses: exactStringArray(value.allowed_uses, ['research_explanation', 'product_display'] as const, 'explanation.allowed_uses'),
  }
}

function normalizeComparator(payload: unknown, meta: NewowProductMeta): NewowComparatorValue {
  const value = exactRecord(payload, 'comparator.value', ['result', 'executable', 'page_parity', 'synthetic_terminal_is_reference_exit', 'allowed_uses'])
  requireExact(value.executable, false, 'comparator.executable'); requireExact(value.page_parity, false, 'comparator.page_parity')
  requireExact(value.synthetic_terminal_is_reference_exit, false, 'comparator.synthetic_terminal_is_reference_exit')
  return { result: value.result === null ? null : normalizeComparatorResult(value.result, meta), executable: false, page_parity: false, synthetic_terminal_is_reference_exit: false, allowed_uses: exactStringArray(value.allowed_uses, ['in_sample_comparison'] as const, 'comparator.allowed_uses') }
}

function normalizeContext(payload: unknown, meta: NewowProductMeta): NewowContextSnapshot {
  const value = exactRecord(payload, 'explanation.context', ['as_of', 'weekly', 'daily', 'hourly', 'missing_frequencies', 'recompute_mode', 'historical_database_knowledge_reconstructed'])
  const asOf = sameInstant(value.as_of, meta.as_of, 'explanation.context.as_of')
  requireExact(value.historical_database_knowledge_reconstructed, false, 'explanation.context.historical_database_knowledge_reconstructed')
  const missing = array(value.missing_frequencies, 'explanation.context.missing_frequencies').map((item, index) => literal(item, FREQUENCIES, `explanation.context.missing_frequencies[${index}]`))
  if (new Set(missing).size !== missing.length) throw new Error('explanation.context.missing_frequencies contains duplicates')
  return { as_of: asOf, weekly: normalizeContextSlot(value.weekly, '1w', meta), daily: normalizeContextSlot(value.daily, '1d', meta), hourly: normalizeContextSlot(value.hourly, '60m', meta), missing_frequencies: missing, recompute_mode: text(value.recompute_mode, 'explanation.context.recompute_mode'), historical_database_knowledge_reconstructed: false }
}

function normalizeContextSlot(payload: unknown, expectedFrequency: NewowProductMeta['identity']['frequency'], meta: NewowProductMeta): NewowContextSlot {
  const field = `explanation.context.${expectedFrequency}`
  const value = exactRecord(payload, field, ['frequency', 'as_of', 'availability', 'confirmation_status', 'identity', 'bar_end', 'source_identity', 'physical_contract', 'segment_id', 'formula_versions', 'main_state'])
  requireExact(value.frequency, expectedFrequency, `${field}.frequency`)
  const identity = value.identity === null ? null : normalizeWireIdentity(value.identity, `${field}.identity`, { ...meta.identity, frequency: expectedFrequency })
  const formulas = stringArray(value.formula_versions, `${field}.formula_versions`)
  if (identity !== null && !sameStrings(formulas, identity.formula_versions)) throw new Error(`${field}.formula_versions conflict with identity`)
  return { frequency: expectedFrequency, as_of: sameInstant(value.as_of, meta.as_of, `${field}.as_of`), availability: normalizeStatus(value.availability, `${field}.availability`), confirmation_status: normalizeStatus(value.confirmation_status, `${field}.confirmation_status`), identity, bar_end: nullableInstant(value.bar_end, `${field}.bar_end`), source_identity: nullableText(value.source_identity, `${field}.source_identity`), physical_contract: value.physical_contract === null ? null : contract(value.physical_contract, `${field}.physical_contract`), segment_id: nullableText(value.segment_id, `${field}.segment_id`), formula_versions: formulas, main_state: value.main_state === null ? null : literal(value.main_state, ['BUILD', 'HOLD', 'CLEAR', 'FLAT', 'UNAVAILABLE'] as const, `${field}.main_state`) }
}

function normalizeSourceFact(payload: unknown, field: string, meta: NewowProductMeta): NewowSourceFact {
  const value = exactRecord(payload, field, ['role', 'source_category', 'adapter_version', 'formula_versions', 'frequency', 'bar_end', 'physical_contract', 'segment_id', 'as_of', 'dependency_sha256', 'status', 'reason_code'])
  return { role: text(value.role, `${field}.role`), source_category: text(value.source_category, `${field}.source_category`), adapter_version: text(value.adapter_version, `${field}.adapter_version`), formula_versions: stringArray(value.formula_versions, `${field}.formula_versions`), frequency: value.frequency === null ? null : literal(value.frequency, FREQUENCIES, `${field}.frequency`), bar_end: nullableInstant(value.bar_end, `${field}.bar_end`), physical_contract: value.physical_contract === null ? null : contract(value.physical_contract, `${field}.physical_contract`), segment_id: nullableText(value.segment_id, `${field}.segment_id`), as_of: sameInstant(value.as_of, meta.as_of, `${field}.as_of`), dependency_sha256: value.dependency_sha256 === null ? null : sha256(value.dependency_sha256, `${field}.dependency_sha256`), status: literal(value.status, ['ready', 'unavailable', 'evidence_required'], `${field}.status`), reason_code: nullableText(value.reason_code, `${field}.reason_code`) }
}

function normalizeCompositeResult(payload: unknown, meta: NewowProductMeta): NewowCompositeResult {
  const field = 'explanation.composite'
  const value = exactRecord(payload, field, ['status', 'evidence_status', 'reason_code', 'as_of', 'formula_versions', 'source_bars', 'value'])
  const status = normalizeStatusFields(value, field)
  return { ...status, as_of: sameInstant(value.as_of, meta.as_of, `${field}.as_of`), formula_versions: stringArray(value.formula_versions, `${field}.formula_versions`), source_bars: array(value.source_bars, `${field}.source_bars`).map((item, index) => normalizeSourceBars(item, `${field}.source_bars[${index}]`, meta)), value: value.value === null ? null : normalizeCompositeValue(value.value, `${field}.value`) }
}

function normalizeSourceBars(payload: unknown, field: string, meta: NewowProductMeta): NewowSourceBars {
  const value = exactRecord(payload, field, ['usage', 'fact_names', 'frequency', 'physical_contract', 'segment_id', 'source_identities', 'count', 'first_bar_end', 'last_bar_end', 'first_trading_day', 'last_trading_day', 'as_of', 'in_sample', 'repainting', 'repaint_status', 'input_status'])
  const first = nullableInstant(value.first_bar_end, `${field}.first_bar_end`); const last = nullableInstant(value.last_bar_end, `${field}.last_bar_end`)
  if (first !== null && last !== null && Date.parse(first) > Date.parse(last)) throw new Error(`${field} source order is invalid`)
  return { usage: text(value.usage, `${field}.usage`), fact_names: stringArray(value.fact_names, `${field}.fact_names`), frequency: literal(value.frequency, FREQUENCIES, `${field}.frequency`), physical_contract: value.physical_contract === null ? null : contract(value.physical_contract, `${field}.physical_contract`), segment_id: nullableText(value.segment_id, `${field}.segment_id`), source_identities: stringArray(value.source_identities, `${field}.source_identities`), count: count(value.count, `${field}.count`), first_bar_end: first, last_bar_end: last, first_trading_day: nullableDay(value.first_trading_day, `${field}.first_trading_day`), last_trading_day: nullableDay(value.last_trading_day, `${field}.last_trading_day`), as_of: sameInstant(value.as_of, meta.as_of, `${field}.as_of`), in_sample: boolean(value.in_sample, `${field}.in_sample`), repainting: boolean(value.repainting, `${field}.repainting`), repaint_status: normalizeStatus(value.repaint_status, `${field}.repaint_status`), input_status: normalizeStatus(value.input_status, `${field}.input_status`) }
}

function normalizeCompositeValue(payload: unknown, field: string): NewowCompositeValue {
  const value = exactRecord(payload, field, ['decision', 'direction', 'certainty', 'volatility', 'first_action', 'week_day_matrix', 'subfeatures', 'input_facts', 'warning_branches_unreachable', 'diagnostic_tokens', 'ai_copy', 'six_combo_ranking', 'evidence_manifest_sha256', 'page_source_sha256', 'reachability_sha256', 'ai_template_evidence_sha256', 'frozen_results_sha256'])
  requireExact(value.diagnostic_tokens, null, `${field}.diagnostic_tokens`); requireExact(value.ai_copy, null, `${field}.ai_copy`); requireExact(value.six_combo_ranking, null, `${field}.six_combo_ranking`)
  return { decision: normalizeCompositeDecision(value.decision, `${field}.decision`), direction: normalizeCompositeDirection(value.direction, `${field}.direction`), certainty: normalizeCertainty(value.certainty, `${field}.certainty`), volatility: value.volatility === null ? null : normalizeVolatility(value.volatility, `${field}.volatility`), first_action: normalizeFirstAction(value.first_action, `${field}.first_action`), week_day_matrix: normalizeWeekDay(value.week_day_matrix, `${field}.week_day_matrix`), subfeatures: array(value.subfeatures, `${field}.subfeatures`).map((item, index) => normalizeSubfeature(item, `${field}.subfeatures[${index}]`)), input_facts: array(value.input_facts, `${field}.input_facts`).map((item, index) => normalizeCompositeInput(item, `${field}.input_facts[${index}]`)), warning_branches_unreachable: boolean(value.warning_branches_unreachable, `${field}.warning_branches_unreachable`), diagnostic_tokens: null, ai_copy: null, six_combo_ranking: null, evidence_manifest_sha256: sha256(value.evidence_manifest_sha256, `${field}.evidence_manifest_sha256`), page_source_sha256: sha256(value.page_source_sha256, `${field}.page_source_sha256`), reachability_sha256: sha256(value.reachability_sha256, `${field}.reachability_sha256`), ai_template_evidence_sha256: sha256(value.ai_template_evidence_sha256, `${field}.ai_template_evidence_sha256`), frozen_results_sha256: sha256(value.frozen_results_sha256, `${field}.frozen_results_sha256`) }
}

function normalizeCompositeDecision(payload: unknown, field: string): NewowCompositeDecision { const v = exactRecord(payload, field, ['source_key', 'selected_key', 'label', 'position_range', 'fallback_used', 'warning_branches_unreachable', 'position_is_target', 'position_is_hand_count', 'formula_version']); return { source_key: text(v.source_key, `${field}.source_key`), selected_key: text(v.selected_key, `${field}.selected_key`), label: text(v.label, `${field}.label`), position_range: text(v.position_range, `${field}.position_range`), fallback_used: boolean(v.fallback_used, `${field}.fallback_used`), warning_branches_unreachable: boolean(v.warning_branches_unreachable, `${field}.warning_branches_unreachable`), position_is_target: boolean(v.position_is_target, `${field}.position_is_target`), position_is_hand_count: boolean(v.position_is_hand_count, `${field}.position_is_hand_count`), formula_version: text(v.formula_version, `${field}.formula_version`) } }
function normalizeCompositeDirection(payload: unknown, field: string): NewowCompositeDirection { const v = exactRecord(payload, field, ['token', 'certainty_points', 'formula_version']); return { token: text(v.token, `${field}.token`), certainty_points: integer(v.certainty_points, `${field}.certainty_points`), formula_version: text(v.formula_version, `${field}.formula_version`) } }
function normalizeCertainty(payload: unknown, field: string): NewowCertaintyBreakdown { const v = exactRecord(payload, field, ['trend', 'oscillation', 'alignment', 'direction', 'uncapped_total', 'total', 'cap', 'is_probability', 'is_win_rate', 'formula_version']); requireExact(v.is_probability, false, `${field}.is_probability`); requireExact(v.is_win_rate, false, `${field}.is_win_rate`); return { trend: integer(v.trend, `${field}.trend`), oscillation: integer(v.oscillation, `${field}.oscillation`), alignment: integer(v.alignment, `${field}.alignment`), direction: integer(v.direction, `${field}.direction`), uncapped_total: integer(v.uncapped_total, `${field}.uncapped_total`), total: integer(v.total, `${field}.total`), cap: v.cap === null ? null : integer(v.cap, `${field}.cap`), is_probability: false, is_win_rate: false, formula_version: text(v.formula_version, `${field}.formula_version`) } }
function normalizeVolatility(payload: unknown, field: string): NewowCompositeVolatility { const v = exactRecord(payload, field, ['value_pct', 'level', 'true_range_count', 'method', 'is_wilder_atr', 'formula_version']); requireExact(v.is_wilder_atr, false, `${field}.is_wilder_atr`); return { value_pct: decimal(v.value_pct, `${field}.value_pct`), level: text(v.level, `${field}.level`), true_range_count: count(v.true_range_count, `${field}.true_range_count`), method: text(v.method, `${field}.method`), is_wilder_atr: false, formula_version: text(v.formula_version, `${field}.formula_version`) } }
function normalizeFirstAction(payload: unknown, field: string): NewowFirstAction { const v = exactRecord(payload, field, ['rule_token', 'level', 'page_title', 'page_detail', 'token_owner', 'token_is_page_native', 'page_formula_version']); requireExact(v.token_is_page_native, false, `${field}.token_is_page_native`); return { rule_token: text(v.rule_token, `${field}.rule_token`), level: text(v.level, `${field}.level`), page_title: text(v.page_title, `${field}.page_title`), page_detail: text(v.page_detail, `${field}.page_detail`), token_owner: text(v.token_owner, `${field}.token_owner`), token_is_page_native: false, page_formula_version: text(v.page_formula_version, `${field}.page_formula_version`) } }
function normalizeWeekDay(payload: unknown, field: string): NewowWeekDayMatrix { const v = exactRecord(payload, field, ['key', 'name', 'risk', 'position', 'formula_version']); return { key: text(v.key, `${field}.key`), name: text(v.name, `${field}.name`), risk: text(v.risk, `${field}.risk`), position: text(v.position, `${field}.position`), formula_version: text(v.formula_version, `${field}.formula_version`) } }
function normalizeCompositeInput(payload: unknown, field: string): NewowCompositeInputFact { const v = exactRecord(payload, field, ['role', 'value', 'frequency', 'bar_end', 'physical_contract', 'segment_id']); return { role: text(v.role, `${field}.role`), value: text(v.value, `${field}.value`), frequency: literal(v.frequency, FREQUENCIES, `${field}.frequency`), bar_end: instant(v.bar_end, `${field}.bar_end`), physical_contract: contract(v.physical_contract, `${field}.physical_contract`), segment_id: text(v.segment_id, `${field}.segment_id`) } }

function normalizeSubfeature(payload: unknown, field: string): NewowSubfeature {
  const v = exactRecord(payload, field, ['name', 'status', 'value']); let parsed: NewowSubfeature['value']
  if (v.value === null || typeof v.value === 'string') parsed = v.value
  else { const item = record(v.value, `${field}.value`); if ('source_key' in item) parsed = normalizeCompositeDecision(item, `${field}.value`); else if ('token' in item) parsed = normalizeCompositeDirection(item, `${field}.value`); else if ('trend' in item) parsed = normalizeCertainty(item, `${field}.value`); else if ('value_pct' in item) parsed = normalizeVolatility(item, `${field}.value`); else if ('rule_token' in item) parsed = normalizeFirstAction(item, `${field}.value`); else if ('key' in item) parsed = normalizeWeekDay(item, `${field}.value`); else throw new Error(`${field}.value has unexpected fields`) }
  return { name: text(v.name, `${field}.name`), status: normalizeStatus(v.status, `${field}.status`), value: parsed }
}

function normalizeTargetResult(payload: unknown, meta: NewowProductMeta): NewowTargetAbsorbResult {
  const field = 'explanation.target_absorb'; const v = exactRecord(payload, field, ['status', 'evidence_status', 'reason_code', 'as_of', 'display_surface', 'formula_versions', 'source_bars', 'decision_facts', 'value']); const status = normalizeStatusFields(v, field)
  return { ...status, as_of: sameInstant(v.as_of, meta.as_of, `${field}.as_of`), display_surface: nullableText(v.display_surface, `${field}.display_surface`), formula_versions: stringArray(v.formula_versions, `${field}.formula_versions`), source_bars: array(v.source_bars, `${field}.source_bars`).map((item, index) => normalizePageFact(item, `${field}.source_bars[${index}]`)), decision_facts: array(v.decision_facts, `${field}.decision_facts`).map((item, index) => normalizePageFact(item, `${field}.decision_facts[${index}]`)), value: v.value === null ? null : normalizeTargetValue(v.value, `${field}.value`) }
}
function normalizePageFact(payload: unknown, field: string): NewowPageFact { const v = exactRecord(payload, field, ['value', 'frequency', 'bar_end', 'physical_contract', 'segment_id']); if (typeof v.value !== 'string' && typeof v.value !== 'boolean') throw new Error(`${field}.value is invalid`); return { value: v.value, frequency: literal(v.frequency, FREQUENCIES, `${field}.frequency`), bar_end: instant(v.bar_end, `${field}.bar_end`), physical_contract: contract(v.physical_contract, `${field}.physical_contract`), segment_id: text(v.segment_id, `${field}.segment_id`) } }
function normalizeTargetValue(payload: unknown, field: string): NewowTargetAbsorbValue { const v = exactRecord(payload, field, ['target', 'absorb', 'previous_close', 'display_surface', 'subfeatures', 'evidence_manifest_sha256', 'inherited_frozen_results_sha256']); requireExact(v.previous_close, null, `${field}.previous_close`); return { target: normalizeTargetPrice(v.target, `${field}.target`), absorb: normalizeTargetPrice(v.absorb, `${field}.absorb`), previous_close: null, display_surface: text(v.display_surface, `${field}.display_surface`), subfeatures: array(v.subfeatures, `${field}.subfeatures`).map((item, index) => { const s = exactRecord(item, `${field}.subfeatures[${index}]`, ['name', 'status', 'value']); return { name: text(s.name, 'name'), status: normalizeStatus(s.status, 'status'), value: nullableText(s.value, 'value') } }), evidence_manifest_sha256: sha256(v.evidence_manifest_sha256, `${field}.evidence_manifest_sha256`), inherited_frozen_results_sha256: sha256(v.inherited_frozen_results_sha256, `${field}.inherited_frozen_results_sha256`) } }
function normalizeTargetPrice(payload: unknown, field: string): NewowTargetDisplayPrice { const v = exactRecord(payload, field, ['raw_value', 'display_value', 'branch', 'source_frequency', 'bar_end', 'physical_contract', 'segment_id']); return { raw_value: decimal(v.raw_value, `${field}.raw_value`), display_value: text(v.display_value, `${field}.display_value`), branch: text(v.branch, `${field}.branch`), source_frequency: literal(v.source_frequency, FREQUENCIES, `${field}.source_frequency`), bar_end: instant(v.bar_end, `${field}.bar_end`), physical_contract: contract(v.physical_contract, `${field}.physical_contract`), segment_id: text(v.segment_id, `${field}.segment_id`) } }

function normalizeComparatorResult(payload: unknown, meta: NewowProductMeta): NewowComparatorResult { const field = 'comparator.result'; const v = exactRecord(payload, field, ['identity', 'status', 'evidence_status', 'reason_code', 'as_of', 'formula_versions', 'source_bars', 'value']); const status = normalizeStatusFields(v, field); return { identity: normalizeWireIdentity(v.identity, `${field}.identity`, meta.identity), ...status, as_of: sameInstant(v.as_of, meta.as_of, `${field}.as_of`), formula_versions: stringArray(v.formula_versions, `${field}.formula_versions`), source_bars: array(v.source_bars, `${field}.source_bars`).map((item, index) => normalizeComparatorSource(item, `${field}.source_bars[${index}]`)), value: v.value === null ? null : normalizeComparatorProduct(v.value, `${field}.value`, meta) } }
function normalizeComparatorSource(payload: unknown, field: string): NewowComparatorSourceBars { const v = exactRecord(payload, field, ['count', 'first_trading_day', 'last_trading_day', 'first_bar_end', 'last_bar_end', 'source_identities', 'snapshot_kind', 'fact_identity_fields']); return { count: count(v.count, `${field}.count`), first_trading_day: nullableDay(v.first_trading_day, `${field}.first_trading_day`), last_trading_day: nullableDay(v.last_trading_day, `${field}.last_trading_day`), first_bar_end: nullableInstant(v.first_bar_end, `${field}.first_bar_end`), last_bar_end: nullableInstant(v.last_bar_end, `${field}.last_bar_end`), source_identities: stringArray(v.source_identities, `${field}.source_identities`), snapshot_kind: text(v.snapshot_kind, `${field}.snapshot_kind`), fact_identity_fields: stringArray(v.fact_identity_fields, `${field}.fact_identity_fields`) } }
function normalizeComparatorProduct(payload: unknown, field: string, meta: NewowProductMeta): NewowComparatorProductValue { const v = exactRecord(payload, field, ['segments', 'default_segment_id', 'candidate_windows', 'page_formula_version', 'futures_adapter_version', 'page_source_kernel_page_parity', 'futures_adapter_page_parity', 'in_sample', 'executable', 'input_mode', 'subfeatures']); requireExact(v.page_source_kernel_page_parity, true, `${field}.page_source_kernel_page_parity`); requireExact(v.futures_adapter_page_parity, false, `${field}.futures_adapter_page_parity`); requireExact(v.in_sample, true, `${field}.in_sample`); requireExact(v.executable, false, `${field}.executable`); const windows = integerArray(v.candidate_windows, `${field}.candidate_windows`); return { segments: array(v.segments, `${field}.segments`).map((item, index) => normalizeComparatorSegment(item, `${field}.segments[${index}]`, meta, windows)), default_segment_id: nullableText(v.default_segment_id, `${field}.default_segment_id`), candidate_windows: windows, page_formula_version: text(v.page_formula_version, `${field}.page_formula_version`), futures_adapter_version: text(v.futures_adapter_version, `${field}.futures_adapter_version`), page_source_kernel_page_parity: true, futures_adapter_page_parity: false, in_sample: true, executable: false, input_mode: text(v.input_mode, `${field}.input_mode`), subfeatures: array(v.subfeatures, `${field}.subfeatures`).map((item, index) => normalizeSubfeature(item, `${field}.subfeatures[${index}]`)) } }
function normalizeComparatorSegment(payload: unknown, field: string, meta: NewowProductMeta, windows: readonly number[]): NewowComparatorSegment { const v = exactRecord(payload, field, ['physical_contract', 'segment_id', 'frequency', 'authoritative_start_trading_day', 'authoritative_end_trading_day', 'source_bars', 'as_of', 'in_sample', 'repainting', 'repaint_status', 'input_snapshot_status', 'status', 'results', 'ranked_windows']); requireExact(v.frequency, meta.identity.frequency, `${field}.frequency`); const results = array(v.results, `${field}.results`).map((item, index) => normalizeWindow(item, `${field}.results[${index}]`)); if (!sameNumbers(results.map((item) => item.window), windows)) throw new Error(`${field}.results do not align with candidate_windows`); const ranked = integerArray(v.ranked_windows, `${field}.ranked_windows`); if (ranked.some((window) => !windows.includes(window)) || new Set(ranked).size !== ranked.length) throw new Error(`${field}.ranked_windows is invalid`); return { physical_contract: contract(v.physical_contract, `${field}.physical_contract`), segment_id: text(v.segment_id, `${field}.segment_id`), frequency: meta.identity.frequency, authoritative_start_trading_day: day(v.authoritative_start_trading_day, `${field}.authoritative_start_trading_day`), authoritative_end_trading_day: day(v.authoritative_end_trading_day, `${field}.authoritative_end_trading_day`), source_bars: normalizeComparatorSource(v.source_bars, `${field}.source_bars`), as_of: sameInstant(v.as_of, meta.as_of, `${field}.as_of`), in_sample: boolean(v.in_sample, `${field}.in_sample`), repainting: boolean(v.repainting, `${field}.repainting`), repaint_status: normalizeStatus(v.repaint_status, `${field}.repaint_status`), input_snapshot_status: normalizeStatus(v.input_snapshot_status, `${field}.input_snapshot_status`), status: normalizeStatus(v.status, `${field}.status`), results, ranked_windows: ranked } }
function normalizeWindow(payload: unknown, field: string): NewowWindowComparison { const v = exactRecord(payload, field, ['window', 'cumulative_return_pct', 'max_drawdown_pct', 'trade_count', 'win_count', 'loss_count', 'win_rate_pct', 'force_closed_at_end', 'score', 'page_display', 'trades']); const wins = count(v.win_count, `${field}.win_count`); const losses = count(v.loss_count, `${field}.loss_count`); const trades = array(v.trades, `${field}.trades`).map((item, index) => normalizeComparatorTrade(item, `${field}.trades[${index}]`)); if (wins + losses !== count(v.trade_count, `${field}.trade_count`) || trades.length !== wins + losses) throw new Error(`${field}.trade counts conflict`); return { window: count(v.window, `${field}.window`), cumulative_return_pct: decimal(v.cumulative_return_pct, `${field}.cumulative_return_pct`), max_drawdown_pct: decimal(v.max_drawdown_pct, `${field}.max_drawdown_pct`), trade_count: trades.length, win_count: wins, loss_count: losses, win_rate_pct: decimal(v.win_rate_pct, `${field}.win_rate_pct`), force_closed_at_end: boolean(v.force_closed_at_end, `${field}.force_closed_at_end`), score: decimal(v.score, `${field}.score`), page_display: normalizeComparatorDisplay(v.page_display, `${field}.page_display`), trades } }
function normalizeComparatorDisplay(payload: unknown, field: string): NewowComparatorDisplay { const v = exactRecord(payload, field, ['cumulative_return_pct', 'max_drawdown_pct', 'win_rate_pct']); return { cumulative_return_pct: decimal(v.cumulative_return_pct, `${field}.cumulative_return_pct`), max_drawdown_pct: decimal(v.max_drawdown_pct, `${field}.max_drawdown_pct`), win_rate_pct: decimal(v.win_rate_pct, `${field}.win_rate_pct`) } }
function normalizeComparatorTrade(payload: unknown, field: string): NewowComparatorTrade { const v = exactRecord(payload, field, ['entry_bar_end', 'entry_price', 'exit_bar_end', 'exit_price', 'return_pct', 'won', 'synthetic_terminal']); const entry = instant(v.entry_bar_end, `${field}.entry_bar_end`); const exit = instant(v.exit_bar_end, `${field}.exit_bar_end`); if (Date.parse(entry) > Date.parse(exit)) throw new Error(`${field} order is invalid`); return { entry_bar_end: entry, entry_price: decimal(v.entry_price, `${field}.entry_price`), exit_bar_end: exit, exit_price: decimal(v.exit_price, `${field}.exit_price`), return_pct: decimal(v.return_pct, `${field}.return_pct`), won: boolean(v.won, `${field}.won`), synthetic_terminal: boolean(v.synthetic_terminal, `${field}.synthetic_terminal`) } }

function normalizeStatusFields(value: Record<string, unknown>, field: string): NewowFeatureStatus { return normalizeStatus({ status: value.status, evidence_status: value.evidence_status, reason_code: value.reason_code }, field) }
function sameInstant(value: unknown, expected: string, field: string): string { const parsed = instant(value, field); if (Date.parse(parsed) !== Date.parse(expected)) throw new Error(`${field} conflicts with generation as_of`); return parsed }
function finiteNumber(value: unknown, field: string): number { if (typeof value !== 'number' || !Number.isFinite(value)) throw new Error(`${field} must be a finite number`); return value }
function integer(value: unknown, field: string): number { if (typeof value !== 'number' || !Number.isInteger(value)) throw new Error(`${field} must be an integer`); return value }
function finiteArray(value: unknown, field: string): number[] { return array(value, field).map((item, index) => finiteNumber(item, `${field}[${index}]`)) }
function integerArray(value: unknown, field: string): number[] { return array(value, field).map((item, index) => integer(item, `${field}[${index}]`)) }
function pairArray(value: unknown, field: string): Array<readonly [string, number]> { return array(value, field).map((item, index) => { const pair = array(item, `${field}[${index}]`); if (pair.length !== 2) throw new Error(`${field}[${index}] must be a pair`); return [text(pair[0], `${field}[${index}][0]`), finiteNumber(pair[1], `${field}[${index}][1]`)] as const }) }
function requireAligned(expected: number, field: string, ...values: ReadonlyArray<readonly unknown[]>): void { if (values.some((items) => items.length !== expected)) throw new Error(`${field} arrays must align with bar_ends`) }
function sameNumbers(left: readonly number[], right: readonly number[]): boolean { return left.length === right.length && left.every((value, index) => value === right[index]) }

function compareDecimal(left: string, right: string): number {
  const l = decimalParts(left)
  const r = decimalParts(right)
  if (l.sign !== r.sign) return l.sign < r.sign ? -1 : 1
  const scale = Math.max(l.scale, r.scale)
  const lv = l.value * 10n ** BigInt(scale - l.scale)
  const rv = r.value * 10n ** BigInt(scale - r.scale)
  return lv === rv ? 0 : (lv < rv ? -l.sign : l.sign)
}

function decimalParts(value: string): { sign: 1 | -1; value: bigint; scale: number } {
  const match = DECIMAL.exec(value)!
  const sign: 1 | -1 = match[0].startsWith('-') ? -1 : 1
  const unsigned = value.replace(/^[+-]/, '')
  const [mantissa, exponentText] = unsigned.toLowerCase().split('e')
  const [whole, fraction = ''] = mantissa!.split('.')
  const digits = `${whole || '0'}${fraction}`.replace(/^0+(?=\d)/, '')
  const exponent = exponentText === undefined ? 0 : Number(exponentText)
  const scale = fraction.length - exponent
  if (scale >= 0) return { sign, value: BigInt(digits || '0'), scale }
  return { sign, value: BigInt(digits || '0') * 10n ** BigInt(-scale), scale: 0 }
}

function decimal(value: unknown, field: string): string {
  if (typeof value !== 'string' || !DECIMAL.test(value)) throw new Error(`${field} must be a finite Decimal string`)
  const exponent = /[eE]([+-]?\d+)$/.exec(value)?.[1]
  if (exponent !== undefined && (!Number.isSafeInteger(Number(exponent)) || Math.abs(Number(exponent)) > 10000)) throw new Error(`${field} Decimal exponent is invalid`)
  return value
}

function nullableDecimal(value: unknown, field: string): string | null { return value === null ? null : decimal(value, field) }
function record(value: unknown, field: string): Record<string, unknown> { if (value === null || typeof value !== 'object' || Array.isArray(value)) throw new Error(`${field} must be an object`); return value as Record<string, unknown> }
function exactRecord(value: unknown, field: string, keys: readonly string[]): Record<string, unknown> { const result = record(value, field); const actual = Object.keys(result); if (actual.length !== keys.length || actual.some((key) => !keys.includes(key)) || keys.some((key) => !(key in result))) throw new Error(`${field} has missing or unexpected fields`); return result }
function array(value: unknown, field: string): unknown[] { if (!Array.isArray(value)) throw new Error(`${field} must be an array`); return value }
function text(value: unknown, field: string): string { if (typeof value !== 'string' || !value.trim()) throw new Error(`${field} must be a non-empty string`); return value }
function nullableText(value: unknown, field: string): string | null { return value === null ? null : text(value, field) }
function productCode(value: unknown, field: string): string { const result = text(value, field); if (!/^[a-z]+$/.test(result)) throw new Error(`${field} is invalid`); return result }
function contract(value: unknown, field: string): string { const result = text(value, field); if (!/^[A-Z]+\d{3,4}$/.test(result)) throw new Error(`${field} is invalid`); return result }
function boolean(value: unknown, field: string): boolean { if (typeof value !== 'boolean') throw new Error(`${field} must be boolean`); return value }
function count(value: unknown, field: string): number { if (typeof value !== 'number' || !Number.isInteger(value) || value < 0) throw new Error(`${field} must be a non-negative integer`); return value }
function literal<T extends string>(value: unknown, values: readonly T[], field: string): T { if (typeof value !== 'string' || !values.includes(value as T)) throw new Error(`${field} is invalid`); return value as T }
function requireExact(value: unknown, expected: unknown, field: string): void { if (value !== expected) throw new Error(`${field} is invalid`) }
function day(value: unknown, field: string): string { if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value)) throw new Error(`${field} must be an ISO date`); const parsed = new Date(`${value}T00:00:00Z`); if (!Number.isFinite(parsed.getTime()) || parsed.toISOString().slice(0, 10) !== value) throw new Error(`${field} is invalid`); return value }
function nullableDay(value: unknown, field: string): string | null { return value === null ? null : day(value, field) }
function instant(value: unknown, field: string): string { if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}T.*(?:Z|[+-]\d{2}:?\d{2})$/.test(value) || !Number.isFinite(Date.parse(value))) throw new Error(`${field} must be an ISO instant with timezone`); day(value.slice(0, 10), field); return value }
function nullableInstant(value: unknown, field: string): string | null { return value === null ? null : instant(value, field) }
function sha256(value: unknown, field: string): string { const result = text(value, field); if (!HASH.test(result)) throw new Error(`${field} must be a lowercase SHA-256`); return result }
function stringArray(value: unknown, field: string): string[] { return array(value, field).map((item, index) => text(item, `${field}[${index}]`)) }
function uniqueStrings(value: unknown, field: string): string[] { const items = stringArray(value, field); if (new Set(items).size !== items.length) throw new Error(`${field} contains duplicates`); return items }
function exactStringArray<T extends readonly string[]>(value: unknown, expected: T, field: string): T { const items = stringArray(value, field); if (!sameStrings(items, expected)) throw new Error(`${field} is invalid`); return items as unknown as T }
function sameStrings(left: readonly string[], right: readonly string[]): boolean { return left.length === right.length && left.every((item, index) => item === right[index]) }
function requireOrderedUnique<T>(items: readonly T[], key: (item: T) => string, field: string): void { for (let index = 1; index < items.length; index += 1) if (key(items[index]!) <= key(items[index - 1]!)) throw new Error(`${field} order must be strictly increasing`) }
function requireTimelineOrder<T extends { bar_end: string }>(items: readonly T[], field: string): void { for (let index = 1; index < items.length; index += 1) if (Date.parse(items[index]!.bar_end) < Date.parse(items[index - 1]!.bar_end)) throw new Error(`${field} order is invalid`) }
function requireSequenceOrder<T extends { bar_end: string; sequence: number }>(items: readonly T[], field: string): void { for (let index = 1; index < items.length; index += 1) { const current = items[index]!; const previous = items[index - 1]!; const currentTime = Date.parse(current.bar_end); const previousTime = Date.parse(previous.bar_end); if (currentTime < previousTime || (currentTime === previousTime && current.sequence <= previous.sequence)) throw new Error(`${field} order is invalid`) } }
function requireReferenceOrder(items: readonly NewowReferenceTrade[]): void { for (let index = 1; index < items.length; index += 1) { const previous = items[index - 1]!; const current = items[index]!; const priorKey = [previous.entry_bar_end, String(previous.entry_sequence).padStart(12, '0'), previous.reference_trade_id].join('|'); const currentKey = [current.entry_bar_end, String(current.entry_sequence).padStart(12, '0'), current.reference_trade_id].join('|'); if (currentKey >= priorKey) throw new Error('reference.items order must be strictly descending') } }

function deepFreeze<T>(value: T): T {
  if (value !== null && typeof value === 'object' && !Object.isFrozen(value)) {
    for (const child of Object.values(value as Record<string, unknown>)) deepFreeze(child)
    Object.freeze(value)
  }
  return value
}
