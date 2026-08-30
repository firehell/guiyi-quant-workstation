import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import {
  buildSubingPerformanceTrend,
  formatSubingMeanHoldingBars,
  nextSubingPerformanceEpisodeLimit,
  subingPerformanceExitReasonRows,
} from '../src/utils/subingStrategyPerformance.ts'
import { normalizeSubingStrategyPerformance } from '../src/types/market.ts'

const root = path.resolve(import.meta.dirname, '..')

test('performance panel defaults to trend view and keeps analysis copy bounded', () => {
  const panel = fs.readFileSync(
    path.join(root, 'src/components/market/SubingStrategyPerformancePanel.vue'),
    'utf8',
  )
  const chart = fs.readFileSync(
    path.join(root, 'src/components/market/SubingPerformanceTrendChart.vue'),
    'utf8',
  )
  assert.match(panel, /ref<PerformancePanelTab>\('trend'\)/)
  assert.match(panel, /累计参考变动走势/)
  assert.match(panel, /查看明细/)
  assert.match(panel, /v-if="activeTab === 'trend'"/)
  assert.match(panel, /data-testid="subing-performance-exit-reasons"/)
  assert.match(panel, /formatSubingMeanHoldingBars\(item\.stats\.mean_holding_15m_bars\)/)
  assert.match(panel, /不代表账户收益、资金曲线或交易指令/)
  assert.doesNotMatch(panel, /策略收益率/)
  assert.doesNotMatch(panel, /累计收益/)
  assert.doesNotMatch(panel, /最大回撤/)
  assert.doesNotMatch(panel, /交易次数/)
  assert.match(chart, /AreaSeries/)
  assert.match(chart, /createChart/)
  assert.match(chart, /height: 240px/)
  assert.match(chart, /resolveChartTheme/)
})

test('product detail keeps one opt-in fixed actual-dominant 15m performance panel', () => {
  const chart = fs.readFileSync(path.join(root, 'src/pages/market/chart.vue'), 'utf8')
  const panel = fs.readFileSync(path.join(root, 'src/components/market/SubingStrategyPerformancePanel.vue'), 'utf8')
  const api = fs.readFileSync(path.join(root, 'src/api/market.ts'), 'utf8')

  assert.match(chart, /<SubingStrategyPerformancePanel/)
  assert.match(chart, /v-if="showSubingStrategyPerformance"/)
  assert.match(chart, /:symbol="symbol"/)
  assert.match(panel, /真实主力 · 15m · 全历史/)
  assert.match(panel, /参考变动/)
  assert.match(api, /subing-strategy\/performance/)
})

test('sidebar no longer owns complete historical strategy records', () => {
  const panel = fs.readFileSync(path.join(root, 'src/components/market/SubingPanel.vue'), 'utf8')
  assert.doesNotMatch(panel, /<SubingStrategyRecords/)
  assert.match(panel, /当前仓位/)
})

test('performance episodes expand locally in fixed groups of twenty', () => {
  assert.equal(nextSubingPerformanceEpisodeLimit(20, 75), 40)
  assert.equal(nextSubingPerformanceEpisodeLimit(40, 75), 60)
  assert.equal(nextSubingPerformanceEpisodeLimit(60, 75), 75)
  assert.equal(nextSubingPerformanceEpisodeLimit(75, 75), 75)
})

test('mean holding bars display as rounded integers across all summary cards', () => {
  assert.equal(formatSubingMeanHoldingBars('5.034482758620689655172413793'), '5')
  assert.equal(formatSubingMeanHoldingBars('5.5'), '6')
  assert.equal(formatSubingMeanHoldingBars('3'), '3')
  assert.equal(formatSubingMeanHoldingBars(null), '—')
  assert.equal(formatSubingMeanHoldingBars('not-a-number'), '—')
  const panel = fs.readFileSync(
    path.join(root, 'src/components/market/SubingStrategyPerformancePanel.vue'),
    'utf8',
  )
  assert.match(panel, /formatSubingMeanHoldingBars\(item\.stats\.mean_holding_15m_bars\)/)
  assert.doesNotMatch(panel, /item\.stats\.mean_holding_15m_bars \?\?/)
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

function closedEpisode(effectiveBarEnd: string, change: string) {
  return {
    reference_change_percent: change,
    exit_action: { effective_bar_end: effectiveBarEnd },
  }
}

test('cumulative reference series adds closed episode changes in exit time order', () => {
  const trend = buildSubingPerformanceTrend(
    [
      closedEpisode('2026-08-20T02:00:00Z', '1.00'),
      closedEpisode('2026-08-10T02:00:00Z', '2.00'),
      closedEpisode('2026-08-15T02:00:00Z', '-0.50'),
    ],
    'all',
    '2026-08-26T07:00:00Z',
  )
  assert.deepEqual(trend.points, [
    { time: Date.parse('2026-08-10T02:00:00Z') / 1000, value: 2 },
    { time: Date.parse('2026-08-15T02:00:00Z') / 1000, value: 1.5 },
    { time: Date.parse('2026-08-20T02:00:00Z') / 1000, value: 2.5 },
  ])
  assert.equal(trend.kpis.cumulativeLabel, '+2.50%')
  assert.equal(trend.kpis.winRateLabel, '+67%')
  assert.equal(trend.kpis.bestWorstLabel, '+2.00% / -0.50%')
  assert.equal(trend.kpis.completedLabel, '3')
})

test('cumulative series keeps the last point when two exits share a timestamp', () => {
  const trend = buildSubingPerformanceTrend(
    [
      closedEpisode('2026-08-20T02:00:00Z', '1.00'),
      closedEpisode('2026-08-20T02:00:00Z', '2.00'),
    ],
    'all',
    '2026-08-26T07:00:00Z',
  )
  assert.deepEqual(trend.points, [
    { time: Date.parse('2026-08-20T02:00:00Z') / 1000, value: 3 },
  ])
  assert.equal(trend.kpis.completedLabel, '2')
})

test('performance trend range is relative to cache cutoff in Shanghai, not wall clock', () => {
  const cutoff = '2026-08-26T07:00:00Z'
  const episodes = [
    closedEpisode('2026-07-25T15:00:00Z', '1.00'),
    closedEpisode('2026-07-25T16:00:00Z', '2.00'),
    closedEpisode('2026-08-01T02:00:00Z', '3.00'),
    closedEpisode('2025-12-31T15:00:00Z', '4.00'),
    closedEpisode('2026-01-01T02:00:00Z', '5.00'),
    { reference_change_percent: '9.00', exit_action: null },
    closedEpisode('2026-08-01T03:00:00Z', 'not-a-number'),
  ]
  const month = buildSubingPerformanceTrend(episodes, '1m', cutoff)
  assert.equal(month.kpis.completedLabel, '2')
  assert.equal(month.kpis.cumulativeLabel, '+5.00%')
  assert.deepEqual(month.points.map((point) => point.value), [2, 5])

  const ytd = buildSubingPerformanceTrend(episodes, 'ytd', cutoff)
  assert.equal(ytd.kpis.completedLabel, '4')
  assert.equal(ytd.kpis.cumulativeLabel, '+11.00%')

  const empty = buildSubingPerformanceTrend(
    [closedEpisode('2025-01-01T00:00:00Z', '1.00')],
    '1m',
    cutoff,
  )
  assert.deepEqual(empty.points, [])
  assert.equal(empty.kpis.cumulativeLabel, '—')
  assert.equal(empty.kpis.winRateLabel, '—')
  assert.equal(empty.kpis.bestWorstLabel, '—')
  assert.equal(empty.kpis.completedLabel, '—')
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
  assert.throws(
    () => normalizeSubingStrategyPerformance({
      ...payload,
      cache_state: 'unavailable',
      cache_identity_sha256: null,
      cache_generated_at: 'not-a-timestamp',
    }),
    /SUBING_STRATEGY_INVALID_RESPONSE/,
  )
  assert.throws(
    () => normalizeSubingStrategyPerformance({
      ...payload,
      coverage: { ...payload.coverage, segment_count: 1.5 },
    }),
    /SUBING_STRATEGY_INVALID_RESPONSE/,
  )
  assert.throws(
    () => normalizeSubingStrategyPerformance({
      ...payload,
      summary: {
        ...payload.summary,
        overall: { ...empty, completed: 1 },
      },
    }),
    /SUBING_STRATEGY_INVALID_RESPONSE/,
  )
  assert.throws(
    () => normalizeSubingStrategyPerformance({
      ...payload,
      exit_reason_counts: [{ reason_code: 'EMA21_BREACH_LONG', count: 0 }],
    }),
    /SUBING_STRATEGY_INVALID_RESPONSE/,
  )
})
