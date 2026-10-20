import assert from 'node:assert/strict'
import test from 'node:test'
import { effectScope, nextTick, ref } from 'vue'
import { buildNewowFixtureEnvelopeForTest } from '../e2e/newow-product.helpers.mjs'
import { buildNewowReferencePartQuery } from '../src/api/newowProduct.ts'
import { useNewowReferenceParts } from '../src/composables/useNewowReferenceParts.ts'
import { normalizeNewowReferencePartResponse, sameNewowReferenceResult } from '../src/utils/newowReferenceParts.ts'
import type { NewowReferencePartRequest } from '../src/types/newowProduct.ts'

const token = 'frozen-token'
const hash = 'a'.repeat(64)
const request: NewowReferencePartRequest = {
  identity: { product: 'rb', strategy: 'trend', frequency: '1d', seriesKind: 'actual_dominant' },
  asOf: '2026-10-15T15:00:00+08:00', snapshotToken: token, part: 'curve', mode: 'closed',
  performanceSince: '2026-01-01', performanceThrough: '2026-10-15',
}
const common = {
  reference_mode: 'closed', performance_since: '2026-01-01', performance_through: '2026-10-15',
  actual_available_through: '2026-10-15', reference_cutoff: request.asOf,
  reference_input_sha256: hash, history_coverage: 'FULL', executable: false, auto_order: false,
  result_hash: 'c'.repeat(64), record_since: '2026-01-01', records_window_limited: false,
  allowed_uses: ['page_parity_reference', 'research_display'],
}

test('panel validates both bounded parts and first display makes one request', async () => {
  const panelRequest = { ...request, part: 'panel' as const }
  const payload = wire({ ...common, reference_part: 'panel', summary: {}, recent_items: [],
    coverage_intervals: [], unavailable_days: [], page_summaries: {},
    curve: { mode: 'closed', points: [], total_points: 0, sampled: false } })
  assert.equal(normalizeNewowReferencePartResponse(payload, panelRequest).value?.reference_part, 'panel')
  const invalid = structuredClone(payload)
  invalid.reference.value.curve = { ...payload.reference.value.curve, mode: 'holding' }
  assert.throws(() => normalizeNewowReferencePartResponse(invalid, panelRequest))
  const raw = buildNewowFixtureEnvelopeForTest('chart', 'trend', '1d')
  const requests: string[] = []
  const scope = effectScope()
  const state = scope.run(() => useNewowReferenceParts(ref({ meta: raw.meta, section: 'chart' as const, ...raw.chart }),
    ref(true), ref(false), async requested => {
      requests.push(requested.part)
      return { meta: raw.meta, section: 'reference', status: { status: 'ready' }, value: {
        ...payload.reference.value, reference_mode: requested.mode,
        curve: { mode: requested.mode, points: [], total_points: 0, sampled: false },
      } } as any
    }))!
  for (let index = 0; index < 8; index++) await Promise.resolve()
  assert.deepEqual(requests, ['panel'])
  assert.equal(state.overview.value?.value?.reference_part, 'overview')
  assert.equal(state.curve.value?.value?.reference_part, 'curve')
  assert.equal(sameNewowReferenceResult(state.overview.value!, state.curve.value!), true)
  scope.stop()
})
function wire(value: Record<string, unknown>) {
  return {
    meta: { identity: { product: 'rb', strategy: 'trend', frequency: '1d', series_kind: 'actual_dominant' },
      as_of: request.asOf, snapshot_token: token, input_content_sha256: hash },
    section: 'reference', chart: { delivery: 'not_requested', status: null, value: null },
    auxiliary: { delivery: 'not_requested', status: null, value: null },
    explanation: { delivery: 'not_requested', status: null, value: null },
    comparator: { delivery: 'not_requested', status: null, value: null },
    reference: { delivery: 'delivered', status: { status: 'ready', evidence_status: 'ACTIVE_CODE_VERIFIED', reason_code: null }, value },
  }
}

test('reference queries request exactly one part and one selected mode', () => {
  const query = buildNewowReferencePartQuery(request)
  assert.equal(query.reference_part, 'curve')
  assert.equal(query.reference_mode, 'closed')
  assert.equal(query.include_fusion, undefined)
  const fusion = buildNewowReferencePartQuery({ ...request, part: 'history', mode: 'fusion_closed', historyLimit: 50, historyBefore: 'opaque' })
  assert.equal(fusion.include_fusion, true)
  assert.equal(fusion.history_limit, 50)
  assert.equal(fusion.history_before, 'opaque')
  assert.throws(() => buildNewowReferencePartQuery({ ...request, part: 'history', historyLimit: 49 }))
  assert.throws(() => buildNewowReferencePartQuery({ ...request, historyLimit: 50 }))
})

test('split curve accepts sampled points and server owned full metrics', () => {
  const payload = wire({ ...common, reference_part: 'curve', curve: { mode: 'closed',
    points: [{ position: 2499, bar_end: request.asOf, trading_day: '2026-10-15', segment_id: 'rb2610',
      physical_contract: 'RB2610', value: '1.25', reference_trade_id: 'trade-1' }],
    total_points: 2500, sampled: true, metrics: { return_percentage_points: '14.5', win_rate_pct: '55.5',
      closed_count: 20, drawdown: '3.25', drawdown_kind: 'reference_equity' }, annualized_pct: '18.4' } })
  const normalized = normalizeNewowReferencePartResponse(payload, request)
  assert.equal(normalized.value?.reference_part, 'curve')
  if (normalized.value?.reference_part === 'curve') {
    assert.equal(normalized.value.curve.total_points, 2500)
    assert.equal(normalized.value.curve.metrics?.closed_count, 20)
  }
  assert.throws(() => normalizeNewowReferencePartResponse({ ...payload, reference: { ...payload.reference,
    value: { ...payload.reference.value, reference_mode: 'holding' } } }, request))
  assert.throws(() => normalizeNewowReferencePartResponse({ ...payload, chart: { delivery: 'delivered', status: {}, value: {} } }, request))
})

test('overview and history remain bounded and bind the same frozen result', () => {
  const overviewRequest = { ...request, part: 'overview' as const }
  const overview = normalizeNewowReferencePartResponse(wire({ ...common, reference_part: 'overview', summary: {},
    coverage_intervals: [], unavailable_days: [], recent_items: [], page_summaries: { ordinary: null, ideal: null } }), overviewRequest)
  const historyRequest = { ...request, part: 'history' as const, historyLimit: 50 }
  const history = normalizeNewowReferencePartResponse(wire({ ...common, reference_part: 'history', items: [], next_before: null }), historyRequest)
  assert.equal(sameNewowReferenceResult(overview, history), true)
  const terminalWithoutNull = normalizeNewowReferencePartResponse(wire({ ...common, reference_part: 'history', items: [] }), historyRequest)
  assert.equal(terminalWithoutNull.value?.reference_part === 'history' && terminalWithoutNull.value.next_before, null)
  const mismatched = normalizeNewowReferencePartResponse(wire({ ...common, reference_input_sha256: 'b'.repeat(64),
    reference_part: 'history', items: [], next_before: null }), historyRequest)
  assert.equal(sameNewowReferenceResult(overview, mismatched), false)
  const changedResult = normalizeNewowReferencePartResponse(wire({ ...common, result_hash: 'd'.repeat(64),
    reference_part: 'history', items: [], next_before: null }), historyRequest)
  assert.equal(sameNewowReferenceResult(overview, changedResult), false)
  assert.throws(() => normalizeNewowReferencePartResponse(wire({ ...common, record_since: '2026-03-01',
    records_window_limited: false, reference_part: 'history', items: [], next_before: null }), historyRequest))
  const independentFusionWire = wire({ ...common,
    reference_mode: 'fusion_closed', record_since: '2025-10-16', records_window_limited: false,
    reference_part: 'history', items: [], next_before: null })
  independentFusionWire.meta.identity.frequency = '60m'
  const independentFusionHistory = normalizeNewowReferencePartResponse(independentFusionWire,
    { ...historyRequest, identity: { ...historyRequest.identity, frequency: '60m' }, mode: 'fusion_closed' })
  assert.equal(independentFusionHistory.value?.record_since, '2025-10-16')
  assert.throws(() => normalizeNewowReferencePartResponse(wire({ ...common, reference_part: 'history',
    items: Array.from({ length: 51 }, (_, index) => ({ reference_trade_id: `t-${index}` })), next_before: null }), historyRequest))
})

test('hidden reference invalidates old identity and aborts in-flight work before it is shown again', async () => {
  const raw = buildNewowFixtureEnvelopeForTest('chart', 'trend', '1d', false, null, { dualMarket: true })
  const current = ref({ meta: raw.meta, section: 'chart' as const, ...raw.chart })
  const visible = ref(true)
  const pending: { request: NewowReferencePartRequest; signal: AbortSignal; resolve: (value: unknown) => void }[] = []
  const scope = effectScope()
  const state = scope.run(() => useNewowReferenceParts(current, visible, ref(false), (requested, options) =>
    new Promise(resolve => pending.push({ request: requested, signal: options.signal, resolve }))))!
  assert.equal(pending.length, 1)
  visible.value = false
  const nextChart = { ...current.value, meta: { ...current.value.meta,
    identity: { ...current.value.meta.identity, product: 'j' }, snapshot_token: 'new-token' } }
  current.value = nextChart
  assert.equal(pending[0]!.signal.aborted, true)
  assert.equal(state.overview.value, null)
  assert.equal(state.curve.value, null)
  assert.equal(pending.length, 1, 'hidden reference must not fetch')
  pending[0]!.resolve({ section: 'reference', meta: raw.meta, value: { ...common, reference_part: 'overview' } })
  await Promise.resolve(); await Promise.resolve()
  assert.equal(state.overview.value, null, 'late old product response must not render')
  visible.value = true
  await nextTick()
  assert.equal(pending.length, 2)
  assert.equal(pending[1]!.request.identity.product, 'j')
  assert.equal(pending[1]!.request.snapshotToken, 'new-token')
  scope.stop()
})

test('history rejects another result after an atomic panel has been accepted', async () => {
  const raw = buildNewowFixtureEnvelopeForTest('chart', 'trend', '1d', false, null, { dualMarket: true })
  const requests: NewowReferencePartRequest[] = []
  const scope = effectScope()
  const state = scope.run(() => useNewowReferenceParts(ref({ meta: raw.meta, section: 'chart' as const, ...raw.chart }),
    ref(true), ref(false), async requested => {
      requests.push(requested)
      const value = requested.part === 'panel'
        ? { ...common, reference_mode: requested.mode, reference_part: 'panel', summary: {}, recent_items: [],
          coverage_intervals: [], unavailable_days: [], page_summaries: {},
          curve: { mode: requested.mode, points: [], total_points: 0, sampled: false } }
        : { ...common, reference_mode: requested.mode, reference_part: 'history', items: [], next_before: null }
      return { meta: { ...raw.meta, input_content_sha256: requested.part === 'panel' ? hash : 'b'.repeat(64) },
        section: 'reference', status: { status: 'ready' }, value } as any
    }))!
  for (let index = 0; index < 8; index++) await Promise.resolve()
  await state.loadHistory()
  assert.deepEqual(requests.map(item => item.part), ['panel', 'history'])
  assert.equal(state.overview.value?.value?.reference_part, 'overview')
  assert.equal(state.history.value, null)
  assert.match(state.historyError.value ?? '', /暂不可用/)
  scope.stop()
})

test('an unavailable overview remains explicit and does not retry on visibility alone', async () => {
  const raw = buildNewowFixtureEnvelopeForTest('chart', 'trend', '1d')
  const visible = ref(true)
  let calls = 0
  const scope = effectScope()
  const state = scope.run(() => useNewowReferenceParts(ref({ meta: raw.meta, section: 'chart' as const, ...raw.chart }),
    visible, ref(false), async () => {
      calls++
      return { meta: raw.meta, section: 'reference', status: { status: 'unavailable', reason_code: 'NEWOW_DATA_UNAVAILABLE' }, value: null } as any
    }))!
  for (let index = 0; index < 4; index++) await Promise.resolve()
  assert.match(state.error.value ?? '', /数据暂不可用/)
  visible.value = false; await nextTick(); visible.value = true; await nextTick()
  assert.equal(calls, 1)
  await state.load(true)
  assert.equal(calls, 2)
  scope.stop()
})

test('explicit history accumulation stops at 300 without treating the cap as server completion', async () => {
  const raw = buildNewowFixtureEnvelopeForTest('chart', 'trend', '1d', false, null, { dualMarket: true })
  const source = ref({ meta: raw.meta, section: 'chart' as const, ...raw.chart })
  const requests: NewowReferencePartRequest[] = []
  const rows = Array.from({ length: 350 }, (_, index) => ({ reference_trade_id: `trade-${index}`,
    status: 'CLOSED', statistics_membership: 'entry_in_window_v1' }))
  const scope = effectScope()
  const state = scope.run(() => useNewowReferenceParts(source, ref(false), ref(false), async requested => {
    requests.push(requested)
    const base = { ...common, reference_mode: requested.mode, performance_through: '2026-09-03' }
    const value = requested.part === 'panel'
      ? { ...base, reference_part: 'panel', summary: {}, recent_items: [], coverage_intervals: [], unavailable_days: [], page_summaries: {},
          curve: { mode: requested.mode, points: [], total_points: 0, sampled: false, metrics: { closed_count: 350 } } }
        : (() => { const start = requested.historyBefore ? Number(requested.historyBefore.slice(7)) : 0
          const end = Math.min(start + 50, rows.length)
          return { ...base, reference_part: 'history', items: rows.slice(start, end), next_before: end < rows.length ? `cursor-${end}` : null } })()
    return { meta: { ...raw.meta, input_content_sha256: hash }, section: 'reference', status: { status: 'ready' }, value } as any
  }))!
  assert.equal(await state.loadCompleteClosed({ performanceSince: '2026-01-01', performanceThrough: '2026-09-03' }), false)
  assert.equal(state.historyRows.value.length, 300)
  assert.equal(state.historyCapped.value, true)
  assert.equal(state.complete.value, false)
  assert.equal(requests.filter(item => item.part === 'history').length, 6)
  scope.stop()
})

test('ideal tab survives strategy switches but never crosses product or period identity', () => {
 const raw=buildNewowFixtureEnvelopeForTest('chart','trend','1d')
 const chart=ref<any>({meta:raw.meta,section:'chart',...raw.chart}),scope=effectScope(),fusion=ref(false)
 const state=scope.run(()=>useNewowReferenceParts(chart,ref(false),fusion))!
 try {
  state.select('page_ideal')
  const previous=chart.value;chart.value=null;assert.equal(state.mode.value,'page_ideal')
  chart.value={...previous,meta:{...previous.meta,identity:{...previous.meta.identity,strategy:'oscillation'},snapshot_token:'next-strategy'}}
  assert.equal(state.mode.value,'page_ideal');assert.equal(state.overview.value,null)
  fusion.value=true;assert.equal(state.mode.value,'fusion_page_ideal')
  chart.value={...chart.value,meta:{...chart.value.meta,identity:{...chart.value.meta.identity,product:'jm'}}}
  assert.equal(state.mode.value,'fusion_page_ordinary')
  state.select('fusion_page_ideal')
  chart.value={...chart.value,meta:{...chart.value.meta,identity:{...chart.value.meta.identity,frequency:'1w'}}}
  assert.equal(state.mode.value,'fusion_page_ordinary')
 }finally{scope.stop()}
})
