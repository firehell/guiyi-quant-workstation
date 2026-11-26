import assert from 'node:assert/strict'
import test from 'node:test'
import { projectMarketReferenceChart } from '../src/utils/newowMarketReference.ts'
import type { BarData } from '../src/types/market.ts'
import type { MarketAfterCloseFrame } from '../src/types/referenceTrading.ts'

const hash = 'a'.repeat(64)
const first = '2026-11-23T07:00:00Z'
const second = '2026-11-24T07:00:00Z'
const bar = (time: string, overrides: Partial<BarData> = {}): BarData => ({
  time, trading_day: time.slice(0, 10), physicalContract: 'JM2701', sourceBarSha256: hash,
  open: 10, high: 12, low: 9, close: 11, volume: 3, ...overrides,
})
const frame = (bar_end: string, overrides: Partial<MarketAfterCloseFrame> = {}): MarketAfterCloseFrame => ({
  bar_end, trading_day: bar_end.slice(0, 10), physical_contract: 'JM2701',
  source_bar_sha256: hash, calculation_segment_id: 'segment-1',
  product: 'jm', strategy: 'trend', frequency: '1d', formula_versions: ['v1'],
  main_state: 'BUILD', main_values: { a: '10.1', b: '10.2' },
  actions: [{ kind: 'BUILD', signal_id: 'signal-1', trade_eligibility: 'ELIGIBLE' }], hints: [],
  ...overrides,
})
const project = (frames: MarketAfterCloseFrame[], bars: BarData[]) => projectMarketReferenceChart(frames, bars, 'jm', 'trend', '1d', 'reference-revision')

test('plots persisted actions and exact numerical lines against matching Canonical Bars', () => {
  const result = project([frame(first), frame(second, { actions: [{ kind: 'CLOSE', source_signal_id: 'fusion-close' }] })], [bar(first), bar(second)])
  assert.deepEqual(result.markers.map(marker => [marker.id, marker.time, marker.shape]), [
    ['signal-1', first, 'arrowUp'], ['fusion-close', second, 'arrowDown'],
  ])
  assert.deepEqual(result.lines[0]?.points, [{ time: first, value: 10.1 }, { time: second, value: 10.1 }])
  assert.equal(result.lines[0]?.sourceRevision, 'reference-revision')
  assert.equal(result.lines[0]?.formulaVersion, 'v1')
})

test('suppresses overlays for live, revised, wrong contract, and ambiguous frames', () => {
  for (const displayed of [
    bar(first, { confirmed: false }), bar(first, { sourceBarSha256: undefined }),
    bar(first, { sourceBarSha256: 'b'.repeat(64) }), bar(first, { physicalContract: 'JM2702' }),
  ]) {
    assert.deepEqual(project([frame(first)], [displayed]).markers, [])
  }
  assert.deepEqual(project([frame(first), frame(first)], [bar(first)]).markers, [])
  assert.deepEqual(project([frame(first, { actions: [{ kind: 'BUILD', signal_id: 'fixture', trade_eligibility: 'WARMUP_ONLY' }] })], [bar(first)]).markers, [])
})

test('does not draw lines across a different calculation segment', () => {
  assert.deepEqual(project([frame(first), frame(second, { calculation_segment_id: 'segment-2' })], [bar(first), bar(second)]).lines, [])
})

test('does not draw a saved line across a different formula identity', () => {
  assert.deepEqual(project([frame(first), frame(second, { formula_versions: ['v2'] })], [bar(first), bar(second)]).lines, [])
})

test('saved auxiliary is read through the archive route and bound to the chart identity and token', async () => {
  const { getMarketAfterCloseSection } = await import('../src/api/referenceTrading.ts')
  const { buildNewowFixtureEnvelopeForTest, NEWOW_AS_OF } = await import('../e2e/newow-product.helpers.mjs')
  const identity = { product: 'rb', strategy: 'trend', frequency: '1d', seriesKind: 'actual_dominant' } as const
  const component = 'main_force_control'
  const chart = buildNewowFixtureEnvelopeForTest('chart', 'trend', '1d', false, null, { component })
  const result = buildNewowFixtureEnvelopeForTest('auxiliary', 'trend', '1d', false, null, { component })
  result.meta.snapshot_token = chart.meta.snapshot_token
  result.meta.data_revision_identity = chart.meta.data_revision_identity
  const query = { identity, asOf: NEWOW_AS_OF, section: 'auxiliary', component } as const
  const saved = await getMarketAfterCloseSection(query, { request: async (url, { params }) => {
    assert.equal(url, '/reference-trading/newow/after-close/section')
    assert.deepEqual(params, { product: 'rb', strategy: 'trend', frequency: '1d', section: 'auxiliary', component })
    return { status: 'ready', receipt: hash, chart, result }
  } })
  assert.equal(saved.status, 'ready')
  assert.equal(saved.chart?.meta.snapshot_token, saved.result?.meta.snapshot_token)
  assert.equal(saved.result?.section, 'auxiliary')
  await assert.rejects(() => getMarketAfterCloseSection(query, { request: async () => ({
    status: 'ready', receipt: hash, chart, result: { ...result, meta: { ...result.meta, snapshot_token: 'mismatched' } },
  }) }), /REFERENCE_SNAPSHOT_CHANGED/)
  await assert.rejects(() => getMarketAfterCloseSection({ ...query, asOf: '2026-01-01T00:00:00Z' }, { request: async () => ({
    status: 'ready', receipt: hash, chart, result,
  }) }), /as_of/)
})

test('missing materialized sections stay pending without borrowing another result', async () => {
  const { getMarketAfterCloseSection } = await import('../src/api/referenceTrading.ts')
  const query = {
    identity: { product: 'rb', strategy: 'oscillation', frequency: '1d', seriesKind: 'actual_dominant' },
    asOf: '2026-11-26T07:00:00Z', section: 'comparator',
  } as const
  const result = await getMarketAfterCloseSection(query, {
    request: async () => ({ status: 'pending', receipt: null, chart: null, result: null }),
  })
  assert.equal(result.result, null)
  await assert.rejects(() => getMarketAfterCloseSection(query, {
    request: async () => ({ status: 'pending', receipt: null, chart: {}, result: null }),
  }), /REFERENCE_RESPONSE_INVALID/)
})

test('reads the unchanged five-window comparator from an archived oscillation section', async () => {
  const { getMarketAfterCloseSection } = await import('../src/api/referenceTrading.ts')
  const { buildNewowFixtureEnvelopeForTest, NEWOW_AS_OF } = await import('../e2e/newow-product.helpers.mjs')
  const identity = { product: 'rb', strategy: 'oscillation', frequency: '1d', seriesKind: 'actual_dominant' } as const
  const chart = buildNewowFixtureEnvelopeForTest('chart', 'oscillation', '1d')
  const result = buildNewowFixtureEnvelopeForTest('comparator', 'oscillation', '1d')
  result.meta.snapshot_token = chart.meta.snapshot_token
  result.meta.data_revision_identity = chart.meta.data_revision_identity
  const saved = await getMarketAfterCloseSection({ identity, asOf: NEWOW_AS_OF, section: 'comparator' }, {
    request: async (_url, { params }) => {
      assert.equal(Object.hasOwn(params, 'component'), false)
      return { status: 'ready', receipt: hash, chart, result }
    },
  })
  assert.equal(saved.result?.section, 'comparator')
  if (saved.result?.section === 'comparator') {
    assert.equal(saved.result.value?.executable, false)
    assert.equal(saved.result.value?.synthetic_terminal_is_reference_exit, false)
  }
})
