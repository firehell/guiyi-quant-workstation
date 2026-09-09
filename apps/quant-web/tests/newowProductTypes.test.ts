import assert from 'node:assert/strict'
import test from 'node:test'
import kernelMacdFixture from '../e2e/fixtures/newow-rich-macd.json' with { type: 'json' }

import {
  getNewowProductSection,
  NewowProductRequestError,
} from '../src/api/newowProduct.ts'
import {
  NEWOW_FREQUENCIES,
  NEWOW_STRATEGIES,
} from '../src/types/marketDetail.ts'
import {
  NEWOW_PRODUCT_FREQUENCIES,
  NEWOW_PRODUCT_STRATEGIES,
} from '../src/types/newowProduct.ts'
import {
  chartCoordinate,
  normalizeNewowProductResponse,
} from '../src/utils/newowProductTypes.ts'
import {
  buildNewowProductSectionViewModel,
  formatDecimalString,
  resolveNewowPanelRenderState,
} from '../src/utils/newowProductViewModel.ts'

const AS_OF = '2026-08-15T07:00:00Z'
const FORMULAS = ['newow_escape_d123_page_v2', 'newow_trend_band_page_v2']
const expected = {
  product: 'jm', strategy: 'trend', frequency: '1d', seriesKind: 'actual_dominant',
  section: 'chart', asOf: AS_OF,
} as const

test('unwraps only the delivered requested section and preserves every Decimal as a string', () => {
  const result = normalizeNewowProductResponse(chartWire(), expected)

  assert.equal(result.section, 'chart')
  assert.equal(result.value.bars[0]!.open, '100.125')
  assert.equal(result.value.frames[0]!.main_values.B, '100.100')
  assert.equal(result.value.actions[0]!.reference_price, '100.100')
  assert.equal(Object.isFrozen(result), true)
  assert.equal(chartCoordinate('100.125'), 100.125)
  assert.throws(() => chartCoordinate('1e999'), /finite chart coordinate/)
})

test('fails closed before unwrap when fields or the five delivery wrappers violate the P4 envelope', () => {
  const missing = chartWire()
  delete (missing.meta as Record<string, unknown>).read_at
  assert.throws(() => normalizeNewowProductResponse(missing, expected), /missing/)

  const leaked = chartWire()
  leaked.reference = { delivery: 'not_requested', status: null, value: { forged: true } }
  assert.throws(() => normalizeNewowProductResponse(leaked, expected), /not_requested/)

  const wrongRequested = chartWire()
  wrongRequested.chart = { delivery: 'not_requested', status: null, value: null }
  assert.throws(() => normalizeNewowProductResponse(wrongRequested, expected), /delivered/)

  const extra = chartWire()
  Object.assign(extra.chart.value!, { private_server_fact: true })
  assert.throws(() => normalizeNewowProductResponse(extra, expected), /unexpected/)
})

test('rejects non-finite Decimal text and wrong contract, frequency, formula, source, or order', () => {
  for (const invalid of ['NaN', 'Infinity', '-Infinity']) {
    const raw = chartWire()
    raw.chart.value!.bars[0]!.close = invalid
    assert.throws(() => normalizeNewowProductResponse(raw, expected), /Decimal/)
  }

  const contract = chartWire()
  contract.chart.value!.bars[0]!.physical_contract = 'jm2601'
  assert.throws(() => normalizeNewowProductResponse(contract, expected), /physical_contract/)

  const frequency = chartWire()
  frequency.meta.identity.frequency = '60m'
  assert.throws(() => normalizeNewowProductResponse(frequency, expected), /frequency/)

  const formula = chartWire()
  formula.meta.identity.formula_versions = ['newow_trend_band_page_v2']
  assert.throws(() => normalizeNewowProductResponse(formula, expected), /formula_versions/)

  const source = chartWire()
  source.chart.value!.bars[0]!.source_identity = ''
  assert.throws(() => normalizeNewowProductResponse(source, expected), /source_identity/)

  const order = chartWire()
  order.chart.value!.actions = [
    action('clear-2', 'CLEAR', 2, '2026-08-14T07:00:00Z'),
    action('build-1', 'BUILD', 1, '2026-08-14T07:00:00Z'),
  ]
  assert.throws(() => normalizeNewowProductResponse(order, expected), /order/)
})

test('shares one Newow strategy and frequency allowlist authority across route and product contracts', () => {
  assert.equal(NEWOW_PRODUCT_STRATEGIES, NEWOW_STRATEGIES)
  assert.equal(NEWOW_PRODUCT_FREQUENCIES, NEWOW_FREQUENCIES)
})

test('rejects chart facts later than the fixed snapshot as_of', () => {
  const bar = chartWire()
  bar.chart.value!.bars[0]!.bar_end = '2026-08-15T07:00:01Z'
  assert.throws(() => normalizeNewowProductResponse(bar, expected), /bars\[0\].bar_end.*as_of/)

  const actionFact = chartWire()
  actionFact.chart.value!.actions[0]!.bar_end = '2026-08-15T07:00:01Z'
  assert.throws(() => normalizeNewowProductResponse(actionFact, expected), /actions\[0\].bar_end.*as_of/)

  const hintBar = chartWire()
  hintBar.chart.value!.hints = [{
    hint_id: 'future-hint', kind: 'D4', bar_end: '2026-08-15T07:00:01Z', known_at: AS_OF,
    anchor_price: null, physical_contract: 'JM2601', segment_id: 'jm:JM2601:2026-01-01T00:00:00+00:00',
    retrospective: false, quantity_effect: 'none', sequence: null,
  }]
  assert.throws(() => normalizeNewowProductResponse(hintBar, expected), /hints\[0\].bar_end.*as_of/)

  const knownAt = chartWire()
  knownAt.chart.value!.hints = [{
    hint_id: 'future-known', kind: 'D4', bar_end: '2026-08-14T07:00:00Z', known_at: '2026-08-15T07:00:01Z',
    anchor_price: null, physical_contract: 'JM2601', segment_id: 'jm:JM2601:2026-01-01T00:00:00+00:00',
    retrospective: false, quantity_effect: 'none', sequence: null,
  }]
  knownAt.chart.value!.frames[0]!.hint_ids = ['future-known']
  assert.throws(() => normalizeNewowProductResponse(knownAt, expected), /hints\[0\].known_at.*as_of/)
})

test('rejects reference cutoff overflow and trade facts outside or against its causal order', () => {
  const cutoff = referenceWire()
  cutoff.reference.value!.reference_cutoff = '2026-08-15T07:00:01Z'
  assert.throws(() => normalizeNewowProductResponse(cutoff, { ...expected, section: 'reference' }), /reference_cutoff.*as_of/)

  const lateFields = [
    ['entry_bar_end', '2026-08-15T07:00:01Z'],
    ['exit_bar_end', '2026-08-15T07:00:01Z'],
    ['mark_bar_end', '2026-08-15T07:00:01Z'],
    ['interrupted_at', '2026-08-15T07:00:01Z'],
  ] as const
  for (const [field, value] of lateFields) {
    const raw = referenceWire()
    ;(raw.reference.value!.items[0]! as Record<string, unknown>)[field] = value
    assert.throws(
      () => normalizeNewowProductResponse(raw, { ...expected, section: 'reference' }),
      new RegExp(`${field}.*reference_cutoff`),
    )
  }

  for (const field of ['exit_bar_end', 'mark_bar_end', 'interrupted_at'] as const) {
    const raw = referenceWire()
    ;(raw.reference.value!.items[0]! as Record<string, unknown>)[field] = '2026-08-13T07:00:00Z'
    assert.throws(
      () => normalizeNewowProductResponse(raw, { ...expected, section: 'reference' }),
      new RegExp(`${field}.*order`),
    )
  }
})

test('binds frames, actions, and hints to the exact returned Bar owner identities', () => {
  const owner = chartWire()
  owner.chart.value!.actions[0]!.physical_contract = 'JM2605'
  assert.throws(() => normalizeNewowProductResponse(owner, expected), /owner/)

  const frame = chartWire()
  frame.chart.value!.frames[0]!.action_ids = ['missing-action']
  assert.throws(() => normalizeNewowProductResponse(frame, expected), /action_ids/)

  const day = chartWire()
  day.chart.value!.actions[0]!.trading_day = '2026-08-15'
  assert.throws(() => normalizeNewowProductResponse(day, expected), /trading_day/)
})

test('orders actions by bar_end then per-Bar sequence and permits sequence reset on the next Bar', () => {
  const reset = chartWire()
  reset.chart.value!.actions[0]!.sequence = 7
  reset.chart.value!.bars.push({ ...reset.chart.value!.bars[0]!, bar_end: '2026-08-15T07:00:00Z', trading_day: '2026-08-15' })
  reset.chart.value!.frames.push({ ...reset.chart.value!.frames[0]!, bar_end: '2026-08-15T07:00:00Z', main_state: 'CLEAR', action_ids: ['clear-2'] })
  reset.chart.value!.actions.push(action('clear-2', 'CLEAR', 0, '2026-08-15T07:00:00Z'))
  assert.doesNotThrow(() => normalizeNewowProductResponse(reset, expected))

  const duplicate = chartWire()
  duplicate.chart.value!.frames[0]!.action_ids.push('clear-2')
  duplicate.chart.value!.actions.push(action('clear-2', 'CLEAR', 1, '2026-08-14T07:00:00Z'))
  assert.throws(() => normalizeNewowProductResponse(duplicate, expected), /order/)
})

test('builds the exact P4 query for every section and omits cross-section parameters', async () => {
  const calls: Array<{ path: string; params: Record<string, unknown>; signal?: AbortSignal }> = []
  const request = async (path: string, config: { params: Record<string, unknown>; signal?: AbortSignal }) => {
    calls.push({ path, ...config })
    const section = config.params.section as 'chart' | 'auxiliary' | 'reference' | 'explanation' | 'comparator'
    return section === 'chart' ? chartWire() : statusWire(section)
  }
  const common = { identity: { product: 'jm', strategy: 'trend', frequency: '1d', seriesKind: 'actual_dominant' as const }, asOf: AS_OF }
  await getNewowProductSection({ ...common, section: 'chart', from: '2026-08-01', through: '2026-08-15', chartLimit: 400, chartBefore: 'opaque-c' }, { request })
  await getNewowProductSection({ ...common, section: 'auxiliary', component: 'cup_handle', from: '2026-08-01', through: '2026-08-15' }, { request })
  await getNewowProductSection({ ...common, section: 'reference', performanceSince: '2025-01-01', performanceThrough: '2026-08-15', historyLimit: 25, historyBefore: 'opaque-r' }, { request })
  await getNewowProductSection({ ...common, section: 'explanation' }, { request })
  await getNewowProductSection({ ...common, section: 'comparator', snapshotToken: 'compatible-token' }, { request })

  assert.deepEqual(calls.map(({ params }) => params), [
    { product: 'jm', strategy: 'trend', frequency: '1d', series_kind: 'actual_dominant', section: 'chart', as_of: AS_OF, from: '2026-08-01', through: '2026-08-15', chart_limit: 400, chart_before: 'opaque-c' },
    { product: 'jm', strategy: 'trend', frequency: '1d', series_kind: 'actual_dominant', section: 'auxiliary', as_of: AS_OF, component: 'cup_handle', from: '2026-08-01', through: '2026-08-15' },
    { product: 'jm', strategy: 'trend', frequency: '1d', series_kind: 'actual_dominant', section: 'reference', as_of: AS_OF, performance_since: '2025-01-01', performance_through: '2026-08-15', history_limit: 25, history_before: 'opaque-r' },
    { product: 'jm', strategy: 'trend', frequency: '1d', series_kind: 'actual_dominant', section: 'explanation', as_of: AS_OF },
    { product: 'jm', strategy: 'trend', frequency: '1d', series_kind: 'actual_dominant', section: 'comparator', as_of: AS_OF, snapshot_token: 'compatible-token' },
  ])
  assert.ok(calls.every(({ path }) => path === '/market/newow/strategy-detail'))
})

test('maps 409 and 429 into safe classified errors without leaking transport details', async () => {
  const cases = [
    [409, 'NEWOW_DATA_UNAVAILABLE', 'unavailable'],
    [409, 'NEWOW_SNAPSHOT_GENERATION_CONFLICT', 'conflict'],
    [429, 'NEWOW_RESOURCE_BUSY', 'busy'],
    [429, 'NEWOW_REQUEST_CANCELLED', 'cancelled'],
  ] as const
  for (const [status, code, classification] of cases) {
    await assert.rejects(
      getNewowProductSection({ identity: expectedIdentity(), section: 'chart', asOf: AS_OF }, {
        request: async () => { throw { response: { status, data: { detail: { code, secret: '/private/token' } } } } },
      }),
      (error: unknown) => {
        assert.equal(error instanceof NewowProductRequestError, true)
        assert.equal((error as NewowProductRequestError).code, code)
        assert.equal((error as NewowProductRequestError).classification, classification)
        assert.doesNotMatch(String(error), /private|token|secret/i)
        return true
      },
    )
  }
})

test('view models distinguish no action, legal zero CLOSED, warming, stale, and input conflict', () => {
  const chart = normalizeNewowProductResponse(chartWire({ actions: [] }), expected)
  const reference = normalizeNewowProductResponse(referenceWire({ closedCount: 0 }), { ...expected, section: 'reference' })
  assert.equal(buildNewowProductSectionViewModel({ section: 'chart', response: chart, lifecycle: 'ready' }).state, 'no_action')
  assert.equal(buildNewowProductSectionViewModel({ section: 'reference', response: reference, lifecycle: 'ready' }).state, 'empty_closed')
  assert.equal(buildNewowProductSectionViewModel({ section: 'chart', response: null, lifecycle: 'warming' }).state, 'warming')
  assert.equal(buildNewowProductSectionViewModel({ section: 'chart', response: chart, lifecycle: 'stale' }).state, 'stale')
  assert.equal(buildNewowProductSectionViewModel({ section: 'chart', response: null, lifecycle: 'input_conflict' }).state, 'input_conflict')
  assert.equal(formatDecimalString('12345678901234567890.5000', 2), '12,345,678,901,234,567,890.50')
})

test('structured missing diagnostics keep safe locations and Chinese recovery guidance', async () => {
  await assert.rejects(getNewowProductSection({ identity: expectedIdentity(), section: 'chart', asOf: AS_OF }, {
    request: async () => { throw { response: { status: 409, data: { detail: {
      code: 'NEWOW_DATA_UNAVAILABLE', diagnostic: { reason: 'REPLAY_PREFIX_MISSING', historical_candidate_recoverable: true,
        context: { symbol: 'rb', contract: 'RB2701', frequency: '60m', trading_day: '2026-09-07', missing_count: 12, path: '/private/fixture', cutoff: 'invalid', actual_count: -1 } },
    } } } } },
  }), (error: unknown) => {
    assert.ok(error instanceof NewowProductRequestError)
    assert.equal(error.code, 'NEWOW_DATA_UNAVAILABLE')
    assert.equal(error.diagnostic?.reason, 'REPLAY_PREFIX_MISSING')
    assert.match(error.message, /预热历史缺失/)
    assert.match(error.message, /RB2701/)
    assert.match(error.message, /历史快照/)
    assert.doesNotMatch(error.message, /private|invalid|-1/)
    return true
  })
})

test('unknown diagnostic reasons cannot advertise historical recovery or reflect text', async () => {
  await assert.rejects(getNewowProductSection({ identity: expectedIdentity(), section: 'chart', asOf: AS_OF }, {
    request: async () => { throw { response: { status: 409, data: { detail: {
      code: 'NEWOW_DATA_UNAVAILABLE', diagnostic: { reason: 'private unknown', historical_candidate_recoverable: true, context: { contract: '/private/fixture' } },
    } } } } },
  }), (error: unknown) => {
    assert.ok(error instanceof NewowProductRequestError)
    assert.equal(error.diagnostic, null)
    assert.doesNotMatch(error.message, /private|历史快照/)
    return true
  })
})

test('legacy data unavailable errors have a Chinese panel message without claiming missing history', () => {
  const message = resolveNewowPanelRenderState('unavailable', null, 'NEWOW_DATA_UNAVAILABLE').message
  assert.match(message, /数据暂不可用/)
  assert.match(message, /重试本面板/)
  assert.doesNotMatch(message, /历史快照/)
})

test('keeps runtime and evidence states independent and accepts validated partial value while warming', () => {
  const raw = referenceWire()
  raw.reference.status = {
    status: 'warming', evidence_status: 'RESEARCH_EVIDENCE_ONLY', reason_code: 'NEWOW_REFERENCE_WEEKLY_WINDOW_PARTIAL',
  }

  const result = normalizeNewowProductResponse(raw, { ...expected, section: 'reference' })

  assert.equal(result.status.status, 'warming')
  assert.equal(result.status.evidence_status, 'RESEARCH_EVIDENCE_ONLY')
  assert.equal(result.value?.summary.closed_count, 1)
})

test('validates auxiliary component data fields and aligned source bars instead of accepting arbitrary JSON', () => {
  const valid = auxiliaryWire()
  const result = normalizeNewowProductResponse(valid, { ...expected, section: 'auxiliary' })
  assert.equal(result.section, 'auxiliary')
  assert.equal(result.value?.segments[0]?.data?.current_status, 'control')

  const extra = auxiliaryWire()
  Object.assign(extra.auxiliary.value!.segments[0]!.data!, { invented: true })
  assert.throws(() => normalizeNewowProductResponse(extra, { ...expected, section: 'auxiliary' }), /unexpected/)

  const misaligned = auxiliaryWire()
  misaligned.auxiliary.value!.segments[0]!.data!.kongpan.push(2)
  assert.throws(() => normalizeNewowProductResponse(misaligned, { ...expected, section: 'auxiliary' }), /align/)

  assert.throws(
    () => normalizeNewowProductResponse(auxiliaryWire(), { identity: expectedIdentity(), section: 'auxiliary', component: 'cup_handle', asOf: AS_OF }),
    /component/,
  )
})

test('binds reference performance windows to the exact section request', () => {
  assert.throws(
    () => normalizeNewowProductResponse(referenceWire(), {
      identity: expectedIdentity(), section: 'reference', asOf: AS_OF,
      performanceSince: '2025-02-01', performanceThrough: '2026-08-15',
    }),
    /performance_since/,
  )
})

test('shared trend explanation context remains valid on oscillation and main-rise pages', () => {
  for (const strategy of ['oscillation', 'main_rise'] as const) {
    const original = explanationWire()
    const formula_versions = strategy === 'oscillation'
      ? ['newow_hhv_llv_channel_page_v1', 'newow_oscillation_hhv_llv10_page_v1']
      : ['newow_buy_d456_page_v1', 'newow_escape_d123_page_v2', 'newow_magic11_page_v1', 'newow_main_rise_j_reduce_page_v1', 'newow_main_rise_ma35_ma45_page_v1']
    const wire = { ...original, meta: { ...original.meta, identity: {
      ...original.meta.identity, strategy, profile_id: `newow_product_${strategy}_1d_v1`, formula_versions,
    } } }
    const request = { ...expected, strategy, section: 'explanation' as const }
    const explanation = normalizeNewowProductResponse(wire, request)
    assert.equal(explanation.meta.identity.strategy, strategy)
    assert.equal(explanation.value?.context.daily.identity?.strategy, 'trend')
    for (const [field, wrong] of Object.entries({
      product: 'au', strategy, frequency: '60m', profile_id: 'newow_product_oscillation_1d_v1', formula_versions: ['unknown_formula'],
    })) {
      const invalid = structuredClone(wire)
      Object.assign(invalid.explanation.value.context.daily.identity!, { [field]: wrong })
      assert.throws(() => normalizeNewowProductResponse(invalid, request), new RegExp(field))
    }
    assert.throws(() => normalizeNewowProductResponse(wire, { ...request, strategy: 'trend' }), /strategy/)
  }
})

test('validates explanation context identities and comparator result identities through the full P4 shape', () => {
  const explanation = normalizeNewowProductResponse(explanationWire(), { ...expected, section: 'explanation' })
  assert.equal(explanation.section, 'explanation')
  assert.equal(explanation.value?.context.daily.identity?.frequency, '1d')

  const wrongContext = explanationWire()
  wrongContext.explanation.value!.context.daily.identity!.frequency = '60m'
  assert.throws(() => normalizeNewowProductResponse(wrongContext, { ...expected, section: 'explanation' }), /frequency/)

  const comparator = normalizeNewowProductResponse(comparatorWire(), { ...expected, section: 'comparator' })
  assert.equal(comparator.section, 'comparator')
  assert.equal(comparator.value?.result?.value?.segments[0]?.results[0]?.page_display.cumulative_return_pct, '1.2500')

  const wrongComparator = comparatorWire()
  wrongComparator.comparator.value!.result!.identity.product = 'rb'
  assert.throws(() => normalizeNewowProductResponse(wrongComparator, { ...expected, section: 'comparator' }), /product/)

  const nonFinite = comparatorWire()
  ;(nonFinite.comparator.value!.result!.value!.segments[0]!.source_bars as { count: number }).count = Number.POSITIVE_INFINITY
  assert.throws(() => normalizeNewowProductResponse(nonFinite, { ...expected, section: 'comparator' }), /integer/)
})

test('preserves unavailable comparator owner segments with fewer than 20 bars and no computed windows', () => {
  const wire = insufficientComparatorWire()
  const response = normalizeNewowProductResponse(wire, { ...expected, section: 'comparator' })
  assert.equal(response.status.status, 'unavailable')
  assert.equal(response.value?.result?.value?.segments[0]?.source_bars.count, 6)
  assert.deepEqual(response.value?.result?.value?.segments[0]?.results, [])
  const panel = resolveNewowPanelRenderState('unavailable', response, null)
  assert.equal(panel.showValue, false)
  assert.match(panel.message, /当前物理合约区段不足 20 根 Bar/)
  assert.match(panel.message, /NEWOW_PAGE_COMPARATOR_INSUFFICIENT_BARS/)
  assert.doesNotMatch(panel.message, /DATA_CONFLICT|NEWOW_RESPONSE_INVALID|加载失败/)
})

test('insufficient comparator status cannot hide computed values, a full source, or malformed identity', () => {
  for (const mutate of [
    (wire: ReturnType<typeof insufficientComparatorWire>) => { wire.comparator.value.result.value.segments[0]!.source_bars.count = 20 },
    (wire: ReturnType<typeof insufficientComparatorWire>) => { wire.comparator.value.result.value.segments[0]!.status.status = 'ready' },
    (wire: ReturnType<typeof insufficientComparatorWire>) => { wire.comparator.value.result.value.segments[0]!.status.evidence_status = 'ACTIVE_CODE_VERIFIED' },
    (wire: ReturnType<typeof insufficientComparatorWire>) => { wire.comparator.value.result.value.segments[0]!.status.reason_code = 'NEWOW_OTHER_UNAVAILABLE' },
    (wire: ReturnType<typeof insufficientComparatorWire>) => { wire.comparator.value.result.value.segments[0]!.ranked_windows.push(4) },
    (wire: ReturnType<typeof insufficientComparatorWire>) => { wire.comparator.value.result.value.segments[0]!.results.push(comparatorWire().comparator.value.result.value.segments[0]!.results[0]!) },
    (wire: ReturnType<typeof insufficientComparatorWire>) => { wire.comparator.value.result.identity.product = 'rb' },
    (wire: ReturnType<typeof insufficientComparatorWire>) => { wire.comparator.value.result.value.segments[0]!.source_bars.count = Infinity },
    (wire: ReturnType<typeof insufficientComparatorWire>) => { wire.comparator.value.result.value.segments[0]!.frequency = '60m' },
  ]) {
    const wire = insufficientComparatorWire()
    mutate(wire)
    assert.throws(() => normalizeNewowProductResponse(wire, { ...expected, section: 'comparator' }))
  }
  const ready = comparatorWire()
  ready.comparator.value.result.value.segments[0]!.results = []
  assert.throws(() => normalizeNewowProductResponse(ready, { ...expected, section: 'comparator' }), /candidate_windows/)
})

function insufficientComparatorWire() {
  const wire = comparatorWire()
  const result = wire.comparator.value.result
  const status = { status: 'unavailable', evidence_status: 'RESEARCH_EVIDENCE_ONLY', reason_code: 'NEWOW_PAGE_COMPARATOR_INSUFFICIENT_BARS' }
  const segment = result.value.segments[0]!
  return {
    ...wire,
    comparator: { ...wire.comparator, status, value: {
      ...wire.comparator.value,
      result: { ...result, ...status, value: { ...result.value, segments: [{
        ...segment, status, source_bars: { ...segment.source_bars, count: 6 },
        results: [] as typeof segment.results, ranked_windows: [] as number[],
      }] } },
    } },
  }
}

export function expectedIdentity(strategy: 'trend' | 'oscillation' | 'main_rise' = 'trend', frequency: '1w' | '1d' | '60m' = '1d') {
  return { product: 'jm', strategy, frequency, seriesKind: 'actual_dominant' as const }
}

export function chartWire(options: { product?: string; strategy?: 'trend' | 'oscillation' | 'main_rise'; frequency?: '1w' | '1d' | '60m'; token?: string | null; hash?: string; actions?: unknown[]; close?: string } = {}) {
  const product = options.product ?? 'jm'
  const strategy = options.strategy ?? 'trend'
  const frequency = options.frequency ?? '1d'
  const formulas = strategy === 'trend' ? FORMULAS : strategy === 'oscillation'
    ? ['newow_hhv_llv_channel_page_v1', 'newow_oscillation_hhv_llv10_page_v1']
    : ['newow_buy_d456_page_v1', 'newow_escape_d123_page_v2', 'newow_magic11_page_v1', 'newow_main_rise_j_reduce_page_v1', 'newow_main_rise_ma35_ma45_page_v1']
  const close = options.close ?? '101.500'
  return {
    meta: {
      schema_version: 'newow_product_detail_v1',
      identity: { product, strategy, frequency, series_kind: 'actual_dominant', profile_id: `newow_product_${strategy}_${frequency}_v1`, formula_versions: formulas },
      as_of: AS_OF, read_at: '2026-08-15T07:00:01Z', input_content_sha256: options.hash ?? 'a'.repeat(64),
      data_revision_identity: null, snapshot_token: options.token === undefined ? 'snapshot-a' : options.token,
      reference_model_version: 'newow_marker_reference_zero_cost_v1', futures_adaptation_version: 'newow_futures_segment_interrupt_v1',
    },
    section: 'chart' as const,
    chart: {
      delivery: 'delivered' as const,
      status: featureStatus('ready'),
      value: {
        chart_from: '2026-08-14', chart_through: '2026-08-15', page_identity: 'b'.repeat(64),
        bars: [{ bar_end: '2026-08-14T07:00:00Z', trading_day: '2026-08-14', open: '100.125', high: '102.000', low: '99.500', close, volume: 10, open_interest: 20, physical_contract: 'JM2601', segment_id: 'jm:JM2601:2026-01-01T00:00:00+00:00', source_identity: 'canonical:jm:JM2601:1d', observation_eligible: true, completed: true }],
        frames: [{ bar_end: '2026-08-14T07:00:00Z', main_state: 'BUILD', main_values: { B: '100.100', nullable: null }, status: featureStatus('ready'), action_ids: options.actions === undefined ? ['build-1'] : [], hint_ids: [] }],
        actions: options.actions ?? [action('build-1', 'BUILD', 1, '2026-08-14T07:00:00Z')],
        hints: [], diagnostics: [], next_before: null, repainting: false, formal_signal_eligible: true,
        allowed_uses: ['product_chart', 'reference_input'],
      },
    },
    auxiliary: notRequested(), reference: notRequested(), explanation: notRequested(), comparator: notRequested(),
  }
}

export function referenceWire(options: { token?: string | null; hash?: string; referenceHash?: string; closedCount?: number; items?: unknown[]; nextBefore?: string | null; performanceSince?: string } = {}) {
  const closedCount = options.closedCount ?? 1
  const base = chartWire({ token: options.token, hash: options.hash })
  return {
    ...base,
    section: 'reference' as const,
    chart: notRequested(),
    reference: {
      delivery: 'delivered' as const,
      status: featureStatus('ready'),
      value: {
        performance_since: options.performanceSince ?? '2025-01-01', performance_through: '2026-08-15', actual_available_through: '2026-08-15',
        reference_cutoff: AS_OF, reference_input_sha256: options.referenceHash ?? 'c'.repeat(64),
        summary: { membership_policy: 'closed_entry_in_requested_window', closed_count: closedCount, win_count: closedCount, loss_count: 0, flat_count: 0, win_rate_pct: closedCount ? '100.00' : null, mean_return_pct: closedCount ? '1.2500' : null, sum_return_percentage_points: closedCount ? '1.2500' : null, open_count: 0, interrupted_count: 0, initial_count: 0 },
        items: options.items ?? (closedCount ? [referenceItem('trade-1', '1.2500')] : []), next_before: options.nextBefore ?? null,
        executable: false, auto_order: false, allowed_uses: ['page_parity_reference', 'research_display'],
      },
    },
  }
}

export function statusWire(section: 'auxiliary' | 'reference' | 'explanation' | 'comparator') {
  const base = chartWire({ token: null })
  const result: Record<string, unknown> = { ...base, section, chart: notRequested() }
  result[section] = { delivery: 'delivered', status: featureStatus('warming', 'NEWOW_TEST_WARMING'), value: null }
  return result
}

function auxiliaryWire() {
  const base = chartWire()
  return {
    ...base, section: 'auxiliary' as const, chart: notRequested(),
    auxiliary: { delivery: 'delivered' as const, status: featureStatus('ready'), value: {
      component: 'main_force_control' as const, formula_version: 'newow_main_force_control_page_v1',
      segments: [{
        physical_contract: 'JM2601', segment_id: 'jm:JM2601:2026-01-01T00:00:00+00:00',
        bar_ends: ['2026-08-14T07:00:00Z'], status: featureStatus('ready'),
        data: { kongpan: [1.25], status: ['control'], current_status: 'control', formula_version: 'newow_main_force_control_page_v1' },
      }],
      repainting: false, formal_signal_eligible: false, page_parity: true,
      source_category: 'guiyi_product_auxiliary_adapter', allowed_uses: ['product_auxiliary'],
    } },
  }
}

function explanationWire() {
  const base = chartWire()
  const emptySlot = (frequency: '1w' | '1d' | '60m') => ({
    frequency, as_of: AS_OF, availability: featureStatus('ready'), confirmation_status: featureStatus('ready'),
    identity: frequency === '1d' ? { ...base.meta.identity } : null,
    bar_end: frequency === '1d' ? '2026-08-14T07:00:00Z' : null,
    source_identity: frequency === '1d' ? 'canonical:jm:JM2601:1d' : null,
    physical_contract: frequency === '1d' ? 'JM2601' : null,
    segment_id: frequency === '1d' ? 'jm:JM2601:2026-01-01T00:00:00+00:00' : null,
    formula_versions: frequency === '1d' ? FORMULAS : [], main_state: frequency === '1d' ? 'BUILD' : null,
  })
  const sourceBars = {
    usage: 'decision', fact_names: ['main_state'], frequency: '1d', physical_contract: 'JM2601',
    segment_id: 'jm:JM2601:2026-01-01T00:00:00+00:00', source_identities: ['canonical:jm:JM2601:1d'], count: 1,
    first_bar_end: '2026-08-14T07:00:00Z', last_bar_end: '2026-08-14T07:00:00Z',
    first_trading_day: '2026-08-14', last_trading_day: '2026-08-14', as_of: AS_OF,
    in_sample: true, repainting: false, repaint_status: featureStatus('ready'), input_status: featureStatus('ready'),
  }
  const pageFact = { value: 'BUILD', frequency: '1d', bar_end: '2026-08-14T07:00:00Z', physical_contract: 'JM2601', segment_id: 'jm:JM2601:2026-01-01T00:00:00+00:00' }
  return {
    ...base, section: 'explanation' as const, chart: notRequested(),
    explanation: { delivery: 'delivered' as const, status: featureStatus('ready'), value: {
      context: { as_of: AS_OF, weekly: emptySlot('1w'), daily: emptySlot('1d'), hourly: emptySlot('60m'), missing_frequencies: ['1w', '60m'], recompute_mode: 'strict_before', historical_database_knowledge_reconstructed: false },
      composite: { status: 'ready', evidence_status: 'ACTIVE_CODE_VERIFIED', reason_code: null, as_of: AS_OF, formula_versions: ['newow_composite_page_v1'], source_bars: [sourceBars], value: null },
      target_absorb: { status: 'ready', evidence_status: 'ACTIVE_CODE_VERIFIED', reason_code: null, as_of: AS_OF, display_surface: 'research', formula_versions: ['newow_target_absorb_page_v1'], source_bars: [pageFact], decision_facts: [pageFact], value: null },
      sources: [{ role: 'daily', source_category: 'canonical', adapter_version: 'v1', formula_versions: FORMULAS, frequency: '1d', bar_end: '2026-08-14T07:00:00Z', physical_contract: 'JM2601', segment_id: 'jm:JM2601:2026-01-01T00:00:00+00:00', as_of: AS_OF, dependency_sha256: 'd'.repeat(64), status: 'ready', reason_code: null }],
      page_parity: false, allowed_uses: ['research_explanation', 'product_display'],
    } },
  }
}

function comparatorWire() {
  const base = chartWire()
  return {
    ...base, section: 'comparator' as const, chart: notRequested(),
    comparator: { delivery: 'delivered' as const, status: featureStatus('ready'), value: {
      result: {
        identity: { ...base.meta.identity }, status: 'ready', evidence_status: 'RESEARCH_EVIDENCE_ONLY', reason_code: null,
        as_of: AS_OF, formula_versions: ['newow_window_comparator_page_v1'],
        source_bars: [{ count: 2, first_trading_day: '2026-08-13', last_trading_day: '2026-08-14', first_bar_end: '2026-08-13T07:00:00Z', last_bar_end: '2026-08-14T07:00:00Z', source_identities: ['canonical:jm:JM2601:1d'], snapshot_kind: 'canonical', fact_identity_fields: ['bar_end', 'physical_contract'] }],
        value: {
          segments: [{
            physical_contract: 'JM2601', segment_id: 'jm:JM2601:2026-01-01T00:00:00+00:00', frequency: '1d', authoritative_start_trading_day: '2026-08-13', authoritative_end_trading_day: '2026-08-14',
            source_bars: { count: 2, first_trading_day: '2026-08-13', last_trading_day: '2026-08-14', first_bar_end: '2026-08-13T07:00:00Z', last_bar_end: '2026-08-14T07:00:00Z', source_identities: ['canonical:jm:JM2601:1d'], snapshot_kind: 'canonical', fact_identity_fields: ['bar_end', 'physical_contract'] },
            as_of: AS_OF, in_sample: true, repainting: false, repaint_status: featureStatus('ready'), input_snapshot_status: featureStatus('ready'), status: featureStatus('ready'),
            results: [{ window: 4, cumulative_return_pct: '1.2500', max_drawdown_pct: '-0.5000', trade_count: 1, win_count: 1, loss_count: 0, win_rate_pct: '100.00', force_closed_at_end: true, score: '1.0000', page_display: { cumulative_return_pct: '1.2500', max_drawdown_pct: '-0.5000', win_rate_pct: '100.00' }, trades: [{ entry_bar_end: '2026-08-13T07:00:00Z', entry_price: '100.00', exit_bar_end: '2026-08-14T07:00:00Z', exit_price: '101.25', return_pct: '1.2500', won: true, synthetic_terminal: true }] }], ranked_windows: [4],
          }],
          default_segment_id: 'jm:JM2601:2026-01-01T00:00:00+00:00', candidate_windows: [4], page_formula_version: 'newow_window_comparator_page_v1', futures_adapter_version: 'newow_futures_comparator_v1', page_source_kernel_page_parity: true, futures_adapter_page_parity: false, in_sample: true, executable: false, input_mode: 'canonical', subfeatures: [],
        },
      },
      executable: false, page_parity: false, synthetic_terminal_is_reference_exit: false, allowed_uses: ['in_sample_comparison'],
    } },
  }
}

export function referenceItem(id: string, returnPct: string) {
  return {
    reference_trade_id: id, product: 'jm', strategy_code: 'trend', frequency: '1d', physical_contract: 'JM2601', segment_id: 'jm:JM2601:2026-01-01T00:00:00+00:00',
    formula_versions: FORMULAS, reference_model_version: 'newow_marker_reference_zero_cost_v1', futures_adaptation_version: 'newow_futures_segment_interrupt_v1',
    entry_signal_id: `entry-${id}`, entry_sequence: 1, entry_bar_end: '2026-08-14T07:00:00Z', entry_trading_day: '2026-08-14', entry_reference_price: '100.100',
    exit_signal_id: `exit-${id}`, exit_bar_end: '2026-08-15T07:00:00Z', exit_trading_day: '2026-08-15', exit_reference_price: '101.35125',
    status: 'CLOSED', holding_bars: 1, reference_return_pct: returnPct, mark_bar_end: null, mark_reference_price: null, mark_change_pct: null,
    interrupted_at: null, interruption_reason: null, statistics_membership: 'CLOSED_ENTRY_IN_WINDOW', hint_ids: [],
  }
}

function action(id: string, kind: 'BUILD' | 'CLEAR', sequence: number, barEnd: string) {
  return { signal_id: id, kind, bar_end: barEnd, trading_day: barEnd.slice(0, 10), reference_price: '100.100', physical_contract: 'JM2601', segment_id: 'jm:JM2601:2026-01-01T00:00:00+00:00', related_build_id: kind === 'CLEAR' ? 'build-1' : null, trade_eligibility: 'ELIGIBLE', sequence }
}

function featureStatus(status: 'ready' | 'warming', reasonCode: string | null = null) {
  return { status, evidence_status: 'ACTIVE_CODE_VERIFIED', reason_code: reasonCode }
}

function notRequested() {
  return { delivery: 'not_requested' as const, status: null, value: null }
}

test('accepts MACD as a distinct read-only branch preserving zero and per-point warming', () => {
  const result = normalizeNewowProductResponse(macdWire(), { ...expected, section: 'auxiliary', component: 'macd' })
  assert.equal(result.value.component, 'macd')
  if (result.value.component !== 'macd') throw new Error('MACD expected')
  assert.equal(result.value.display_adapter_version, 'guiyi_newow_macd_display_v1')
  assert.equal(result.value.parameters_hash, '5dd0ebd25122eea6')
  assert.equal(result.value.segments[0]!.data!.dif[0]!.value, 0)
  assert.deepEqual(result.value.segments[0]!.data!.dea[0], {
    bar_end: '2026-08-14T07:00:00Z', value: null, ready: false, valid: true, reason: 'warming_up',
  })
})

test('rejects MACD malformed point states, times, identities, parameters and permission claims', () => {
  const mutations = [
    (wire: ReturnType<typeof macdWire>) => { wire.auxiliary.value.segments[0]!.data.dif[0]!.value = NaN },
    (wire: ReturnType<typeof macdWire>) => { wire.auxiliary.value.segments[0]!.data.dif.pop() },
    (wire: ReturnType<typeof macdWire>) => { wire.auxiliary.value.segments[0]!.data.dif[0]!.bar_end = AS_OF },
    (wire: ReturnType<typeof macdWire>) => { wire.auxiliary.value.segments[0]!.data.dif[0]!.ready = false },
    (wire: ReturnType<typeof macdWire>) => { wire.auxiliary.value.segments[0]!.data.dif[0]!.valid = false },
    (wire: ReturnType<typeof macdWire>) => { wire.auxiliary.value.segments[0]!.data.dea[0]!.reason = null },
    (wire: ReturnType<typeof macdWire>) => { wire.auxiliary.value.segments[0]!.physical_contract = 'RB2601' },
    (wire: ReturnType<typeof macdWire>) => { wire.auxiliary.value.segments.push(wire.auxiliary.value.segments[0]!) },
    (wire: ReturnType<typeof macdWire>) => { wire.auxiliary.value.parameters.fast = 10 },
    (wire: ReturnType<typeof macdWire>) => { wire.auxiliary.value.parameters_hash = 'bad' },
    (wire: ReturnType<typeof macdWire>) => { wire.auxiliary.value.parameters_hash = 'a'.repeat(64) },
    (wire: ReturnType<typeof macdWire>) => { wire.auxiliary.value.parameters_hash = '5DD0EBD25122EEA6' },
    (wire: ReturnType<typeof macdWire>) => { wire.auxiliary.value.formal_signal_eligible = true },
    (wire: ReturnType<typeof macdWire>) => { wire.auxiliary.value.allowed_uses = ['alert'] },
  ]
  for (const mutate of mutations) {
    const wire = macdWire(); mutate(wire)
    assert.throws(() => normalizeNewowProductResponse(wire, { ...expected, section: 'auxiliary', component: 'macd' }))
  }
})

function macdWire() {
  const base = auxiliaryWire()
  const time = '2026-08-14T07:00:00Z'
  const point = (ready: boolean) => ({ bar_end: time, value: ready ? 0 : null as number | null, ready, valid: true, reason: ready ? null : 'warming_up' as string | null })
  return { ...base, auxiliary: { ...base.auxiliary, value: {
    ...base.auxiliary.value, component: 'macd' as const, formula_version: 'v1-draft',
    display_adapter_version: 'guiyi_newow_macd_display_v1',
    parameters: { fast: 12, slow: 26, signal: 9, ema_seed_policy: 'sma_window', histogram_scale: 2, round_digits: 6 },
    parameters_hash: kernelMacdFixture['trend:1d'].parameters_hash, page_parity: false, allowed_uses: ['research_display'],
    segments: [{ ...base.auxiliary.value.segments[0]!, data: { dif: [point(true)], dea: [point(false)], histogram: [point(false)] } }],
  } } }
}
