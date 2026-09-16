import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { normalizeSubingReference, subingCallouts } from '../src/utils/subingReference.ts'
import { useSubingReference } from '../src/composables/useSubingReference.ts'
import { formatMarketDecimal } from '../src/utils/marketDisplay.ts'

export const referenceFixture = (symbol = 'jm') => ({ symbol, frequency: '15m', series_kind: 'actual_dominant', formula_version: 'subing_ths_15m_v3', reference_model_version: 'subing_reference_reverse_close_v1', as_of: '2026-09-08T16:00:00+08:00', performance_since: '2026-08-12', performance_through: '2026-09-08', reference_cutoff: '2026-09-08T15:00:00+08:00', input_snapshot_hash: 'a'.repeat(64), executable: false, auto_order: false, source: 'historical_replay', summary: { closed_count: 0, win_count: 0, loss_count: 0, flat_count: 0, open_count: 0, interrupted_count: 0, initial_count: 0, win_rate_pct: null, mean_return_pct: null, sum_return_percentage_points: '0' }, signals: [], items: [], next_before: null })

test('reference normalizer rejects wrong authority and unsafe financial values', () => {
  assert.equal(normalizeSubingReference(referenceFixture(), 'jm').summary.sum_return_percentage_points, '0')
  for (const patch of [{ symbol: 'rb' }, { executable: true }, { auto_order: true }, { formula_version: 'old' }, { source: 'events' }, { summary: { ...referenceFixture().summary, mean_return_pct: 1.2 } }]) assert.throws(() => normalizeSubingReference({ ...referenceFixture(), ...patch }, 'jm'))
})

test('chart callouts use compact price lines and Chinese-market return colors', () => {
  const [build, profitableReverse, losingReverse, sameDirection] = subingCallouts([
    { signal_id: 'build', bar_end: '2026-09-03T02:30:00Z', trading_day: '2026-09-03', physical_contract: 'JM2601', segment_id: 'segment', direction: 'buy', reference_price: '24.560000', action: 'OPEN_LONG', entry_trade_id: 'open', closed_trade_id: null, closed_return_pct: null },
    { signal_id: 'gain', bar_end: '2026-09-03T02:45:00Z', trading_day: '2026-09-03', physical_contract: 'JM2601', segment_id: 'segment', direction: 'sell', reference_price: '24.080000', action: 'REVERSE_TO_SHORT', entry_trade_id: 'short', closed_trade_id: 'long', closed_return_pct: '0.730000' },
    { signal_id: 'loss', bar_end: '2026-09-03T03:00:00Z', trading_day: '2026-09-03', physical_contract: 'JM2601', segment_id: 'segment', direction: 'buy', reference_price: '23.370000', action: 'REVERSE_TO_LONG', entry_trade_id: 'long', closed_trade_id: 'short', closed_return_pct: '-1.270000' },
    { signal_id: 'same', bar_end: '2026-09-03T03:15:00Z', trading_day: '2026-09-03', physical_contract: 'JM2601', segment_id: 'segment', direction: 'buy', reference_price: '23.510000', action: 'SAME_DIRECTION', entry_trade_id: null, closed_trade_id: null, closed_return_pct: null },
  ])

  assert.deepEqual(build, { id: 'build', time: '2026-09-03T02:30:00Z', physicalContract: 'JM2601', price: '24.560000', title: '建仓', detail: '建仓价: 24.56', tone: 'neutral', above: false })
  assert.deepEqual(profitableReverse, { id: 'gain', time: '2026-09-03T02:45:00Z', physicalContract: 'JM2601', price: '24.080000', title: '平多·开空', detail: '24.08 (+0.73%)', tone: 'gain', above: true })
  assert.deepEqual(losingReverse, { id: 'loss', time: '2026-09-03T03:00:00Z', physicalContract: 'JM2601', price: '23.370000', title: '平空·开多', detail: '23.37 (-1.27%)', tone: 'loss', above: false })
  assert.deepEqual(sameDirection, { id: 'same', time: '2026-09-03T03:15:00Z', physicalContract: 'JM2601', price: '23.510000', title: '同向·不加仓', detail: '23.51', tone: 'neutral', above: false })
})
test('late historical result cannot overwrite switched symbol or disposed loader', async () => {
  let resolve!: (value: unknown) => void
  const loader = useSubingReference((symbol) => symbol === 'jm' ? new Promise((done) => { resolve = done }) : Promise.resolve(referenceFixture(symbol)))
  const first = loader.refresh('jm')
  await loader.refresh('rb')
  resolve(referenceFixture())
  await first
  assert.equal(loader.data.value?.symbol, 'rb')
  loader.dispose()
})
test('page identity mismatch clears historical facts and preserves explicit unavailable state', async () => {
  let calls = 0
  const loader = useSubingReference(async () => ++calls === 1 ? { ...referenceFixture(), next_before: 'cursor' } : { ...referenceFixture(), input_snapshot_hash: 'b'.repeat(64) })
  await loader.refresh('jm')
  await loader.loadMore()
  assert.equal(loader.data.value, null)
  assert.match(loader.error.value ?? '', /快照/)
})

test('known bounded backend diagnostics get a Chinese explanation and unknown text is not reflected', async () => {
  const loader = useSubingReference(async () => { throw {
    response: { status: 409, data: { detail: {
      code: 'SUBING_REFERENCE_DATA_UNAVAILABLE',
      diagnostic: { stage: 'physical_contract_replay', reason: 'DATASET_OR_PARTITION_MISSING', context: { symbol: 'jm', contract: 'JM2609', frequency: '15m', expected_count: 5081, secret: 'do-not-show' } },
    } } },
  } })
  await loader.refresh('jm')
  assert.match(loader.error.value ?? '', /物理合约回放.*行情数据集或分区缺失.*JM2609.*5081/)
  assert.doesNotMatch(loader.error.value ?? '', /secret|do-not-show/)
  const unknown = useSubingReference(async () => { throw {
    response: { status: 409, data: { detail: { code: 'SUBING_REFERENCE_DATA_UNAVAILABLE', diagnostic: { stage: 'evil', reason: 'raw internal stack', context: { path: '/secret' } } } } },
  } })
  await unknown.refresh('jm')
  assert.equal(unknown.error.value, '历史参考不可用，请核查数据覆盖或重新读取。实际预警记录独立展示。')
})

test('callout density falls back to compact passive markers without overlapping labels', async () => {
  const { layoutReferenceCallouts } = await import('../src/utils/referenceCalloutLayout.ts')
  const result = layoutReferenceCallouts(Array.from({ length: 20 }, (_, i) => ({ x: 130 + i, y: 190, callout: { id: String(i), time: '', physicalContract: 'JM2601', price: '100', title: '开多', detail: '100', tone: 'neutral' as const, above: false } })), 360, 400)
  assert.ok(result.some((item) => item.compact))
  const cards = result.filter((item) => !item.compact)
  for (let i = 0; i < cards.length; i++) for (let j = i + 1; j < cards.length; j++) assert.ok(cards[i].left + cards[i].width <= cards[j].left || cards[j].left + cards[j].width <= cards[i].left || cards[i].top + cards[i].height <= cards[j].top || cards[j].top + cards[j].height <= cards[i].top)
})

test('explicit date identity mismatch is unavailable and failed refresh removes previous signals', async () => {
  const loader = useSubingReference(async () => referenceFixture())
  await loader.refresh('jm')
  await loader.refresh('jm', { through: '2026-09-04' })
  assert.equal(loader.data.value, null)
  assert.ok(loader.error.value)
})
test('pagination pins date window and as_of, without deriving or replacing summary', async () => {
  const calls: unknown[] = []
  const loader = useSubingReference(async (_symbol, query) => { calls.push(query); return { ...referenceFixture(), next_before: calls.length === 1 ? 'first-page' : null } })
  await loader.refresh('jm')
  const summary = { ...loader.data.value!.summary }
  await loader.loadMore()
  assert.deepEqual(calls[1], { since: '2026-08-12', through: '2026-09-08', as_of: '2026-09-08T16:00:00+08:00', before: 'first-page' })
  assert.deepEqual(loader.data.value?.summary, summary)
})
test('disposed refresh never publishes historical data', async () => {
  let resolve!: (value: unknown) => void
  const loader = useSubingReference(() => new Promise(done => { resolve = done }))
  const pending = loader.refresh('jm'); loader.dispose(); resolve(referenceFixture()); await pending
  assert.equal(loader.data.value, null)
})

test('same timestamp with another or missing physical owner is never a reference anchor', async () => {
  const { matchesReferenceBar } = await import('../src/utils/referenceCalloutLayout.ts')
  const callout = { time: '2026-09-03T02:45:00Z', physicalContract: 'JM2601' }
  assert.equal(matchesReferenceBar(callout, { time: callout.time, physicalContract: 'JM2605' }), false)
  assert.equal(matchesReferenceBar(callout, { time: callout.time }), false)
  assert.equal(matchesReferenceBar(callout, { time: '2026-09-03T10:45:00+08:00', physicalContract: 'JM2601' }), true)
})

test('display rounds Decimal text without binary floating point or changing raw financial facts', async () => {
  const { referenceDecimalDisplay } = await import('../src/utils/subingReference.ts')
  assert.equal(referenceDecimalDisplay('1.235000000000000000000000001'), '+1.24')
  assert.equal(referenceDecimalDisplay('-0.004'), '0.00')
  assert.equal(referenceDecimalDisplay('99999999999999999999.995'), '+100000000000000000000.00')
  assert.equal(referenceDecimalDisplay('66.666666666666666666', false), '66.67')
})

test('reference prices keep exact Decimal display text without meaningless trailing zeroes', () => {
  assert.equal(formatMarketDecimal('718.070000000000000000'), '718.07')
})

test('reference records separate precise chart location from detail inspection', () => {
  const panel = readFileSync(new URL('../src/components/market/detail/subing/SubingReferencePanel.vue', import.meta.url), 'utf8')
  const workspace = readFileSync(new URL('../src/components/market/detail/subing/SubingDetailWorkspace.vue', import.meta.url), 'utf8')
  assert.match(panel, />定位图表</)
  assert.match(panel, />查看详情</)
  assert.match(panel, /formatMarketDecimal\(trade\.entry_reference_price\)/)
  assert.match(panel, /开始交易日不能晚于结束交易日/)
  assert.match(workspace, /chartRegion\.value\?\.scrollIntoView/)
})
