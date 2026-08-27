import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import {
  nextSubingPerformanceEpisodeLimit,
  subingPerformanceExitReasonRows,
} from '../src/utils/subingStrategyPerformance.ts'
import { normalizeSubingStrategyPerformance } from '../src/types/market.ts'

const root = path.resolve(import.meta.dirname, '..')

test('product detail owns one always-visible fixed actual-dominant 15m performance panel', () => {
  const chart = fs.readFileSync(path.join(root, 'src/pages/market/chart.vue'), 'utf8')
  const panel = fs.readFileSync(path.join(root, 'src/components/market/SubingStrategyPerformancePanel.vue'), 'utf8')
  const api = fs.readFileSync(path.join(root, 'src/api/market.ts'), 'utf8')

  assert.match(chart, /<SubingStrategyPerformancePanel/)
  assert.match(chart, /:symbol="symbol"/)
  assert.match(panel, /真实主力 · 15m · 全历史/)
  assert.match(panel, /参考变动/)
  assert.match(api, /subing-strategy\/performance/)
})

test('sidebar no longer owns complete historical strategy records', () => {
  const panel = fs.readFileSync(path.join(root, 'src/components/market/SubingPanel.vue'), 'utf8')
  assert.doesNotMatch(panel, /<SubingStrategyRecords/)
  assert.match(panel, /当前策略状态/)
})

test('performance episodes expand locally in fixed groups of twenty', () => {
  assert.equal(nextSubingPerformanceEpisodeLimit(20, 75), 40)
  assert.equal(nextSubingPerformanceEpisodeLimit(40, 75), 60)
  assert.equal(nextSubingPerformanceEpisodeLimit(60, 75), 75)
  assert.equal(nextSubingPerformanceEpisodeLimit(75, 75), 75)
})

test('performance exit reasons reuse the strategy record labels', () => {
  assert.deepEqual(subingPerformanceExitReasonRows([
    { reason_code: 'EMA21_BREACH_LONG', count: 3 },
    { reason_code: 'MACD_HIGH_DEAD_CROSS', count: 2 },
  ]), [
    { code: 'EMA21_BREACH_LONG', label: 'EMA21 跌破', count: 3 },
    { code: 'MACD_HIGH_DEAD_CROSS', label: 'MACD 高位死叉', count: 2 },
  ])
})

test('performance wire contract requires exact product cache identity facts', () => {
  const empty = {
    completed: 0, positive: 0, negative: 0, flat: 0,
    positive_rate_percent: null, mean_reference_change_percent: null,
    median_reference_change_percent: null, best_reference_change_percent: null,
    worst_reference_change_percent: null, mean_holding_15m_bars: null,
  }
  const payload = {
    strategy_id: 'subing_strategy_v1', formula_version: 'subing_strategy_15m_v1',
    symbol: 'jm', series_kind: 'actual_dominant', frequency: '15m',
    coverage: {
      since: '2020-01-02', through: '2026-08-26',
      resolved_cutoff: '2026-08-26T07:00:00Z', segment_count: 1,
      bar_count_15m: 20, context_unavailable_count: 0,
    },
    cache_state: 'refreshed', cache_identity_sha256: '1'.repeat(64),
    cache_generated_at: '2026-08-27T08:00:00Z',
    summary: { overall: empty, long: empty, short: empty, open_episodes: 0 },
    exit_reason_counts: [], episodes: [],
  }

  assert.equal(normalizeSubingStrategyPerformance(payload).cache_state, 'refreshed')
  assert.throws(
    () => normalizeSubingStrategyPerformance({ ...payload, cache_identity_sha256: null }),
    /SUBING_STRATEGY_INVALID_RESPONSE/,
  )
})
