import assert from 'node:assert/strict'
import test from 'node:test'

import type { HtdyAlertEvent } from '../src/types/market.ts'

const identity = {
  view: 'htdy' as const,
  symbol: 'jm',
  seriesKind: 'actual_dominant' as const,
  frequency: '15m' as const,
}
const header = {
  asOf: '2026-09-03T02:45:00Z', freshness: 'fresh' as const, extendedSections: [],
} as const

test('keeps current repainting observation and first-seen Event as separate facts', async () => {
  const { buildHtdyDetailViewModel } = await import('../src/utils/htdyDetailViewModel.ts')
  const model = buildHtdyDetailViewModel({
    identity,
    header: header as never,
    rawObservation: '买观察',
    rawUnavailable: false,
    events: [event('sell')],
    alertUnavailable: false,
    runtime: 'healthy',
  })
  assert.match(model.semanticBanner.text, /未来函数/)
  assert.match(model.semanticBanner.text, /不可用于严格回测或交易/)
  assert.deepEqual(model.facts.map((fact) => [fact.source, fact.value]), [
    ['htdy_display', '买观察'],
    ['alert_event', '卖出观察'],
    ['runtime', '运行正常'],
  ])
  assert.equal(model.history[0]?.source, 'alert_event')
  assert.match(model.history[0]?.label ?? '', /首次识别/)
})

test('keeps Event history unavailable explicit without fabricating a current observation', async () => {
  const { buildHtdyDetailViewModel } = await import('../src/utils/htdyDetailViewModel.ts')
  const model = buildHtdyDetailViewModel({
    identity: { ...identity, seriesKind: 'continuous' },
    header: header as never,
    rawObservation: null,
    rawUnavailable: true,
    events: [],
    alertUnavailable: false,
    runtime: 'degraded',
  })
  assert.equal(model.facts[0].value, '当前观察不可用')
  assert.match(model.facts[1].value, /仅属于真实主力序列/)
  assert.equal(model.facts[2].value, '运行降级')
  assert.deepEqual(model.history, [])
})

function event(direction: 'buy' | 'sell'): HtdyAlertEvent {
  return {
    id: 1, rule_code: 'htdy_original_15m', symbol: 'jm', contract: 'JM2601', trading_day: '2026-09-03',
    frequency: '15m', bar_end: '2026-09-03T02:45:00Z', result_codes: [direction],
    detected_at: '2026-09-03T02:46:00Z', notification_attempted_at: null,
  }
}
