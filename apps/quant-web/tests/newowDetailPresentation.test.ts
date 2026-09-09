import assert from 'node:assert/strict'
import test from 'node:test'
import { buildNewowFixtureEnvelopeForTest } from '../e2e/newow-product.helpers.mjs'
import { projectNewowDetail, priceDirection } from '../src/utils/newowDetailPresentation.ts'
const response = (section) => { const raw = buildNewowFixtureEnvelopeForTest(section); return { meta: raw.meta, section, ...raw[section] } }
const chart = () => response('chart')
test('state is the eligible last frame with its actual date, never inferred from an action', () => {
  for (const state of ['BUILD', 'HOLD', 'CLEAR', 'FLAT', 'UNAVAILABLE']) {
    const response = chart()
    response.value.frames.at(-1).main_state = state
    assert.equal(projectNewowDetail(response, 'ready').status.state, state)
  }
  const response = chart()
  response.value.frames = []
  assert.equal(projectNewowDetail(response, 'ready').status.state, 'UNAVAILABLE')
  assert.equal(projectNewowDetail(chart(), 'stale').status.state, 'UNAVAILABLE')
})
test('historical window is explicitly labelled and unloaded sections invent no numbers', () => {
  const response = chart()
  response.value.chart_through = '2025-12-01'
  const model = projectNewowDetail(response, 'ready')
  assert.equal(model.status.historical, true)
  assert.equal(model.target, null)
  assert.equal(model.openReference, null)
})
test('target requires compatible snapshot, status and source identity', () => {
  const c = chart()
  const e = response('explanation')
  assert.equal(projectNewowDetail(c, 'ready', e, 'ready', false).target, null)
  e.meta.as_of = '2020-01-01T00:00:00Z'
  assert.equal(projectNewowDetail(c, 'ready', e, 'ready', true).target, null)
})
test('price badge preserves neutral zero and rejects missing values', () => {
  assert.deepEqual([null, 0, 1, -1].map(priceDirection), ['neutral', 'neutral', 'up', 'down'])
})
test('proven target retains original price strings and source time, rejecting stale or wrong owner facts', () => {
  const c = chart(); const e = response('explanation'); const latest = c.value.bars.at(-1)
  const price = { raw_value: '0108.2500', display_value: '108.2500', branch: 'fixture', source_frequency: '1d', bar_end: latest.bar_end, physical_contract: latest.physical_contract, segment_id: latest.segment_id }
  e.value.target_absorb = { ...e.value.target_absorb, status: 'ready', evidence_status: 'ACTIVE_CODE_VERIFIED', reason_code: null, value: { target: price, absorb: { ...price, display_value: '98.5000' } } }
  assert.equal(projectNewowDetail(c, 'ready', e, 'ready', true).target.display_value, '108.2500')
  assert.equal(projectNewowDetail(c, 'ready', e, 'ready', true).target.bar_end, latest.bar_end)
  assert.equal(projectNewowDetail(c, 'ready', e, 'stale', true).target, null)
  e.value.target_absorb.value.target = { ...price, physical_contract: 'OTHER' }
  assert.equal(projectNewowDetail(c, 'ready', e, 'ready', true).target, null)
})
test('reference summary requires ready compatible current identity and never derives floating returns', () => {
  const c = chart(); const r = response('reference')
  assert.equal(projectNewowDetail(c, 'ready', null, 'not_requested', false, r, 'ready', false).openReference, null)
  const open = projectNewowDetail(c, 'ready', null, 'not_requested', false, r, 'ready', true).openReference
  assert.equal(open.mark_change_pct, '-1.2500')
  assert.equal(projectNewowDetail(c, 'ready', null, 'not_requested', false, r, 'stale', true).openReference, null)
})
test('short state and enum labels remain deterministic and unknown values are unavailable', async () => {
  const { describeNewowState, newowDisplayLabel, shortNewowTime } = await import('../src/utils/newowDetailPresentation.ts')
  assert.equal(describeNewowState('HOLD'), '策略当前为持有状态，仅作页面参考，不代表账户持仓。')
  assert.equal(newowDisplayLabel('BUILD'), '参考建仓')
  assert.equal(newowDisplayLabel('LONG_BIAS'), '偏多')
  assert.equal(newowDisplayLabel('UNKNOWN_NEW_TOKEN'), '未确认')
  assert.equal(shortNewowTime('2026-09-03T07:00:00Z'), '09-03 15:00')
})
test('historical chart state description never claims to describe current snapshot state', async () => {
  const { describeNewowState } = await import('../src/utils/newowDetailPresentation.ts')
  const description = describeNewowState('HOLD', true)
  assert.match(description, /历史.*持有/)
  assert.doesNotMatch(description, /当前/)
})

test('reference percentage display preserves server decimals and never treats missing as zero', async () => {
  const { referencePercentDisplay, referenceInterruptionLabel } = await import('../src/utils/newowDetailPresentation.ts')
  assert.deepEqual(referencePercentDisplay('5.1020'), { text: '+5.1020%', direction: 'up' })
  assert.deepEqual(referencePercentDisplay('-1.2500'), { text: '-1.2500%', direction: 'down' })
  assert.deepEqual(referencePercentDisplay('-0.0000'), { text: '-0.0000%', direction: 'neutral' })
  assert.deepEqual(referencePercentDisplay(null), { text: '—', direction: 'neutral' })
  assert.deepEqual(referencePercentDisplay('unknown'), { text: '—', direction: 'neutral' })
  assert.equal(referenceInterruptionLabel('OWNER_BOUNDARY'), '物理合约区段结束')
  assert.equal(referenceInterruptionLabel('UNVERIFIED'), '中断原因待确认（见详情）')
})

test('reference dates preserve night-session clock, daily density and cross-year identity', async () => {
  const { referenceTimeDisplay } = await import('../src/utils/newowDetailPresentation.ts')
  assert.equal(referenceTimeDisplay('2026-09-03T14:00:00Z', '60m', ['2026-09-04T07:00:00Z']), '09-03 22:00')
  assert.equal(referenceTimeDisplay('2026-09-03T07:00:00Z', '1d', []), '2026-09-03')
  assert.equal(referenceTimeDisplay('2026-09-04T07:00:00Z', '1w', []), '2026-09-04')
  assert.equal(referenceTimeDisplay('2025-12-31T14:00:00Z', '60m', ['2026-01-02T07:00:00Z']), '2025-12-31 22:00')
  assert.equal(referenceTimeDisplay('2026-01-02T07:00:00Z', '60m', ['2025-12-31T14:00:00Z']), '2026-01-02 15:00')
  assert.equal(referenceTimeDisplay(null, '60m', []), '—')
})
