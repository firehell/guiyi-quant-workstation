import type {
  NewowReferenceMode, NewowReferencePartRequest, NewowReferencePartResponse,
  NewowReferencePartValue, NewowReferenceRecord,
} from '../types/newowProduct.ts'

const HASH = /^[0-9a-f]{64}$/
const DECIMAL = /^[+-]?(?:(?:0|[1-9]\d*)(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$/
export const MAX_ACCUMULATED_REFERENCE_TRADES = 300

function object(value: unknown): Record<string, unknown> {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) throw Error('reference object missing')
  return value as Record<string, unknown>
}
function text(value: unknown): string {
  if (typeof value !== 'string' || value.length === 0) throw Error('reference text missing')
  return value
}
function day(value: unknown): string {
  const raw = text(value)
  if (!/^\d{4}-\d{2}-\d{2}$/.test(raw) || Number.isNaN(Date.parse(`${raw}T00:00:00Z`))) throw Error('reference day invalid')
  return raw
}
function instant(value: unknown): string {
  const raw = text(value)
  if (!/T.*(?:Z|[+-]\d{2}:\d{2})$/.test(raw) || Number.isNaN(Date.parse(raw))) throw Error('reference instant invalid')
  return raw
}
function decimal(value: unknown): string {
  const raw = text(value)
  if (!DECIMAL.test(raw) || !Number.isFinite(Number(raw))) throw Error('reference decimal invalid')
  return raw
}
function count(value: unknown): number {
  if (!Number.isSafeInteger(value) || Number(value) < 0) throw Error('reference count invalid')
  return value as number
}
function records(value: unknown, mode: NewowReferenceMode, limit: number): readonly NewowReferenceRecord[] {
  if (!Array.isArray(value) || value.length > limit) throw Error('reference record page invalid')
  const ids = new Set<string>()
  for (const raw of value) {
    const row = object(raw)
    const id = mode.includes('page_')
      ? JSON.stringify([instant(row.buyDate), decimal(row.buyPrice), instant(row.sellDate), decimal(row.sellPrice), decimal(row.pct), text(row.segment_id)])
      : text(row.reference_trade_id)
    if (ids.has(id)) throw Error('duplicate reference record')
    ids.add(id)
  }
  return value as NewowReferenceRecord[]
}

/** Reject old mixed responses and any response from another frozen chart/window/mode. */
export function normalizeNewowReferencePartResponse(payload: unknown, request: NewowReferencePartRequest): NewowReferencePartResponse {
  const top = object(payload), meta = object(top.meta), identity = object(meta.identity)
  if (top.section !== 'reference' || identity.product !== request.identity.product
    || identity.strategy !== request.identity.strategy || identity.frequency !== request.identity.frequency
    || identity.series_kind !== request.identity.seriesKind || meta.as_of !== request.asOf
    || meta.snapshot_token !== request.snapshotToken || !HASH.test(text(meta.input_content_sha256))) {
    throw Error('reference snapshot identity conflict')
  }
  const wrapper = object(top.reference)
  if (wrapper.delivery !== 'delivered') throw Error('reference part not delivered')
  for (const other of ['chart', 'auxiliary', 'explanation', 'comparator']) {
    const inactive = object(top[other])
    if (inactive.delivery !== 'not_requested' || inactive.status !== null || inactive.value !== null) throw Error('mixed reference response rejected')
  }
  const status = object(wrapper.status)
  if (!['ready', 'warming', 'unavailable', 'not_applicable', 'evidence_required'].includes(text(status.status))) throw Error('reference status invalid')
  if (wrapper.value === null) {
    if (status.status === 'ready') throw Error('ready reference part missing')
    return { meta: meta as unknown as NewowReferencePartResponse['meta'], section: 'reference', status: status as unknown as NewowReferencePartResponse['status'], value: null }
  }
  const value = object(wrapper.value)
  if (value.reference_part !== request.part || value.reference_mode !== request.mode
    || !HASH.test(text(value.reference_input_sha256))
    || !HASH.test(text(value.result_hash))
    || value.executable !== false || value.auto_order !== false
    || !Array.isArray(value.allowed_uses)
    || value.allowed_uses.join('|') !== 'page_parity_reference|research_display') throw Error('reference part contract invalid')
  const since = day(value.performance_since), through = day(value.performance_through), recordSince = day(value.record_since)
  const fullWindowRecords = request.mode.includes('page_') || request.identity.frequency === '1d' || request.identity.frequency === '1w'
  const independentFusionRecords = request.mode.startsWith('fusion_') && !fullWindowRecords
  day(value.actual_available_through)
  instant(value.reference_cutoff)
  if (since > through || recordSince > through
    || value.records_window_limited !== (recordSince > since)
    || (fullWindowRecords && recordSince !== since)
    || (!independentFusionRecords && recordSince < since)
    || request.performanceSince !== undefined && since !== request.performanceSince
    || request.performanceThrough !== undefined && through !== request.performanceThrough
    || !['FULL', 'PARTIAL'].includes(text(value.history_coverage))) throw Error('reference window conflict')
  if (request.part === 'panel') {
    // Validate each existing contract against the same envelope, without a
    // second network read or a second calculation of the selected mode.
    const { curve, ...overview } = value
    const { summary: _summary, coverage_intervals: _coverage, unavailable_days: _gaps,
      recent_items: _recent, page_summaries: _page, fusion_groups: _fusion, ...selected } = value
    for (const [part, projected] of [['overview', overview], ['curve', selected]] as const) {
      normalizeNewowReferencePartResponse({ ...top, reference: { ...wrapper, value: { ...projected, reference_part: part } } },
        { ...request, part })
    }
    if (curve === undefined) throw Error('panel curve missing')
  } else if (request.part === 'overview') {
    object(value.summary); object(value.page_summaries)
    if (!Array.isArray(value.coverage_intervals) || !Array.isArray(value.unavailable_days)) throw Error('reference overview invalid')
    records(value.recent_items, request.mode, 3)
    if (value.items !== undefined || value.curve !== undefined || value.next_before !== undefined) throw Error('mixed overview rejected')
  } else if (request.part === 'curve') {
    const curve = object(value.curve)
    const totalPoints = count(curve.total_points)
    if (curve.mode !== request.mode || !Array.isArray(curve.points) || curve.points.length > 2000
      || totalPoints < curve.points.length || typeof curve.sampled !== 'boolean'
      || (curve.sampled !== (totalPoints > curve.points.length))) throw Error('reference curve budget invalid')
    if (curve.summary !== undefined && curve.summary !== null) object(curve.summary)
    if (curve.metrics !== undefined && curve.metrics !== null) {
      const metrics = object(curve.metrics)
      count(metrics.closed_count)
      for (const field of ['return_percentage_points', 'win_rate_pct', 'drawdown']) {
        if (metrics[field] !== null && metrics[field] !== undefined) decimal(metrics[field])
      }
    }
    if (curve.annualized_pct !== undefined && curve.annualized_pct !== null) decimal(curve.annualized_pct)
    let previous = -Infinity
    let previousPosition = -1
    for (const raw of curve.points) {
      const point = object(raw), at = Date.parse(instant(point.bar_end))
      day(point.trading_day); text(point.segment_id)
      if (point.value !== null) decimal(point.value)
      const position = count(point.position)
      if (at < previous || position <= previousPosition || position >= totalPoints) throw Error('reference curve chronology invalid')
      previous = at
      previousPosition = position
      if (!request.mode.includes('page_') && request.mode !== 'holding' && !request.mode.endsWith('_holding')) {
        text(point.reference_trade_id)
        if (point.trade !== undefined && object(point.trade).reference_trade_id !== point.reference_trade_id) throw Error('curve trade identity conflict')
      }
    }
    if (value.items !== undefined || value.recent_items !== undefined || value.next_before !== undefined) throw Error('mixed curve rejected')
  } else {
    records(value.items, request.mode, 50)
    if (value.next_before !== null && value.next_before !== undefined) text(value.next_before)
    if (value.curve !== undefined || value.summary !== undefined || value.recent_items !== undefined) throw Error('mixed history rejected')
  }
  const normalizedValue = request.part === 'history' && value.next_before === undefined
    ? { ...value, next_before: null } : value
  return { meta: meta as unknown as NewowReferencePartResponse['meta'], section: 'reference', status: status as unknown as NewowReferencePartResponse['status'], value: normalizedValue as unknown as NewowReferencePartValue }
}

export function sameNewowReferenceResult(left: NewowReferencePartResponse, right: NewowReferencePartResponse, sameWindow = true): boolean {
  const a = left.value, b = right.value
  return a !== null && b !== null
    && left.meta.snapshot_token === right.meta.snapshot_token
    && left.meta.input_content_sha256 === right.meta.input_content_sha256
    && left.meta.as_of === right.meta.as_of
    && left.meta.identity.product === right.meta.identity.product
    && left.meta.identity.strategy === right.meta.identity.strategy
    && left.meta.identity.frequency === right.meta.identity.frequency
    && a.reference_mode === b.reference_mode
    && a.reference_input_sha256 === b.reference_input_sha256
    && a.result_hash === b.result_hash
    && a.record_since === b.record_since
    && a.records_window_limited === b.records_window_limited
    && a.reference_cutoff === b.reference_cutoff
    && (!sameWindow || a.performance_since === b.performance_since
      && a.performance_through === b.performance_through)
}
