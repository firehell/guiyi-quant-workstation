import assert from 'node:assert/strict'
import test from 'node:test'

import type { MarketDetailHeaderModel } from '../src/types/marketDetail.ts'

const identity = {
  view: 'free' as const,
  symbol: 'jm',
  seriesKind: 'actual_dominant' as const,
  frequency: '15m' as const,
}

const header: MarketDetailHeaderModel = {
  symbol: 'jm', productName: '焦煤', exchange: 'DCE', sector: '黑色',
  seriesKind: 'actual_dominant', displayContract: 'JM2601', asOf: '2026-09-02T02:45:00Z',
  open: 100, high: 101, low: 99, close: 100, change: 1, pct: 1,
  volume: 10, turnover: null, openInterest: null, phase: 'TRADING',
  displaySource: '实时观察', freshness: 'fresh', extendedSections: [],
}

test('free exposes identity facts and never strategy history', async () => {
  const { buildFreeDetailViewModel } = await import('../src/utils/freeDetailViewModel.ts')
  const model = buildFreeDetailViewModel({
    identity,
    header,
    research: null,
    researchError: false,
    rangeState: 'disabled',
  })

  assert.deepEqual(model.facts.map((item) => item.label), ['当前序列', '当前周期', '数据状态'])
  assert.equal(model.facts.length, 3)
  assert.deepEqual(model.history, [])
  assert.equal(model.view, 'free')
  assert.match(model.semanticBanner.text, /不生成策略结论/)
})

test('free formats all supported series kinds and periods as market facts', async () => {
  const { buildFreeDetailViewModel } = await import('../src/utils/freeDetailViewModel.ts')
  const seriesKinds = [
    ['continuous', '主连'],
    ['actual_dominant', '真实主力'],
    ['contract', '指定合约'],
  ] as const
  const periods = [
    ['1m', '1分钟'], ['5m', '5分钟'], ['15m', '15分钟'], ['30m', '30分钟'],
    ['60m', '60分钟'], ['1d', '日K'], ['1w', '周K'],
  ] as const

  for (const [seriesKind, label] of seriesKinds) {
    const model = buildFreeDetailViewModel({
      identity: { ...identity, seriesKind, ...(seriesKind === 'contract' ? { contract: 'JM2601' } : {}) },
      header: { ...header, seriesKind },
      research: null,
      researchError: false,
      rangeState: 'disabled',
    })
    assert.equal(model.facts[0].value, label)
  }
  for (const [frequency, label] of periods) {
    const model = buildFreeDetailViewModel({
      identity: { ...identity, frequency }, header, research: null, researchError: false, rangeState: 'disabled',
    })
    assert.equal(model.facts[1].value, label)
  }
})

test('free reports ready, stale, and unavailable data states without a strategy conclusion', async () => {
  const { buildFreeDetailViewModel } = await import('../src/utils/freeDetailViewModel.ts')
  const expected = [['fresh', '正常'], ['stale', '旧快照'], ['unavailable', '不可用']] as const

  for (const [freshness, dataStatus] of expected) {
    const model = buildFreeDetailViewModel({
      identity, header: { ...header, freshness }, research: null, researchError: false, rangeState: 'disabled',
    })
    assert.equal(model.facts[2].value, dataStatus)
  }
})

test('free handles research errors and every Range state without fabricating a strategy conclusion', async () => {
  const { buildFreeDetailViewModel } = await import('../src/utils/freeDetailViewModel.ts')
  for (const rangeState of ['disabled', 'ready', 'loading', 'insufficient'] as const) {
    const model = buildFreeDetailViewModel({
      identity,
      header: { ...header, freshness: 'stale' },
      research: null,
      researchError: true,
      rangeState,
    })

    assert.equal(model.view, 'free')
    assert.equal(model.history.length, 0)
    assert.equal('score' in model, false)
    if (rangeState !== 'disabled') {
      assert.match(model.semanticBanner.text, /Range Detector 只读回画展示；确认前不可用于策略判断。/)
    }
    if (rangeState === 'loading') assert.match(model.semanticBanner.text, /箱体历史预载中；Range Detector/)
    if (rangeState === 'insufficient') assert.match(model.semanticBanner.text, /箱体历史预载不足；Range Detector/)
    if (rangeState === 'disabled' || rangeState === 'ready') assert.match(model.semanticBanner.text, /不生成策略结论/)
  }
})
