import test from 'node:test'
import assert from 'node:assert/strict'
import { computed, ref } from 'vue'
import { useSubingObservation } from '../src/composables/useSubingObservation.ts'
import {
  filterBarsToSubingSegment,
  isSubingSupportedFrequency,
  shouldScheduleSubingCompanionRefresh,
  subingLifecycleStageLabel,
  subingSignalLabel,
  normalizeSubingResearch,
  type BarData,
  type SubingResearchResponse,
} from '../src/types/market.ts'
import { lifecycleSnapshotToMarkers } from '../src/utils/subingLifecycleMarkers.ts'
import { cloneSubingLifecycleCase } from './fixtures/subingLifecycleCases.mjs'

const readyPayload = cloneSubingLifecycleCase('longSetup') as SubingResearchResponse

test('normalizes Decimal Factor values at the SuBing HTTP boundary', () => {
  const result = normalizeSubingResearch(readyPayload)

  assert.equal(result.primary.snapshot?.slope_5_bps_per_bar, 2)
  assert.equal(result.primary.snapshot?.macd_zero_distance_bps, 15)
  assert.equal(result.primary.snapshot?.volume_ratio_prev, 1)
})

test('normalizes the complete additive lifecycle contract without changing Factor values', () => {
  const result = normalizeSubingResearch(
    cloneSubingLifecycleCase('pivotRetest1') as SubingResearchResponse,
  )

  assert.equal(result.primary.snapshot?.slope_5_bps_per_bar, 2)
  assert.equal(result.companion?.status, 'ready')
  assert.equal(result.lifecycle.bound_reference_pivot?.price, 110)
  assert.equal(result.lifecycle.rebreak_reference_price, 115)
  assert.equal(result.lifecycle.volume_ratio_prev, 3)
  assert.equal(result.lifecycle.open_interest_delta, 18)
  assert.equal(result.lifecycle.latest_transition?.to_stage, 'setup_armed')
})

test('keeps research lifecycle labels separate from formal V1 signal labels', () => {
  assert.equal(subingLifecycleStageLabel('setup_armed'), '准备中')
  assert.equal(subingLifecycleStageLabel('entry_confirmed'), '研究确认')
  assert.equal(subingLifecycleStageLabel('continuation'), '延续')
  assert.equal(subingLifecycleStageLabel('exit_risk'), '退出风险')
  assert.equal(subingLifecycleStageLabel('closed'), '本轮结束')
  assert.equal(subingLifecycleStageLabel('idle'), '暂无机会')
  for (const label of ['准备中', '研究确认', '延续', '退出风险', '本轮结束', '暂无机会']) {
    assert.doesNotMatch(label, /买入|卖出|下单|加仓|平仓指令/i)
  }
})

test('maps only current immutable lifecycle facts to neutral research markers', () => {
  const lifecycle = normalizeSubingResearch(
    cloneSubingLifecycleCase('shortExitRiskFirst') as SubingResearchResponse,
  ).lifecycle
  const key = lifecycle.opportunity_key!
  const transitionId = lifecycle.latest_transition!.transition_id

  assert.deepEqual(lifecycleSnapshotToMarkers(lifecycle), [
    { id: `lifecycle:${key}:entry`, time: '2026-01-12T02:00:00Z', label: '研究确认', tooltip: 'SuBing 生命周期研究 · 研究确认', tone: 'neutral', position: 'belowBar', shape: 'circle' },
    { id: `lifecycle:${key}:transition:${transitionId}`, time: '2026-01-12T02:10:00Z', label: '风险', tooltip: 'SuBing 生命周期研究 · 风险', tone: 'neutral', position: 'belowBar', shape: 'circle' },
  ])
})

test('maps a confirmed hard close to its immutable entry and close facts', () => {
  const lifecycle = (cloneSubingLifecycleCase('oppositeContextClosed') as SubingResearchResponse).lifecycle
  const markers = lifecycleSnapshotToMarkers(lifecycle)
  const key = lifecycle.opportunity_key!
  const transitionId = lifecycle.latest_transition!.transition_id

  assert.deepEqual(markers, [
    { id: `lifecycle:${key}:entry`, time: '2026-01-12T02:00:00Z', label: '研究确认', tooltip: 'SuBing 生命周期研究 · 研究确认', tone: 'neutral', position: 'belowBar', shape: 'circle' },
    { id: `lifecycle:${key}:transition:${transitionId}`, time: '2026-01-12T02:15:00Z', label: '结束', tooltip: 'SuBing 生命周期研究 · 结束', tone: 'neutral', position: 'belowBar', shape: 'circle' },
  ])
})

test('filters old same-contract bars before the current dominant segment', () => {
  const bars: BarData[] = [
    bar('2026-07-15T02:25:00Z', '2026-07-15'),
    bar('2026-08-11T02:25:00Z', '2026-08-11'),
    bar('2026-08-12T02:25:00Z', '2026-08-12'),
    bar('2026-08-13T02:25:00Z', '2026-08-13'),
  ]

  const result = filterBarsToSubingSegment(bars, '2026-08-12')

  assert.deepEqual(result.map((item) => item.trading_day), ['2026-08-12', '2026-08-13'])
})

test('keeps an insufficient companion explicit without inventing a Factor snapshot', () => {
  const payload = cloneSubingLifecycleCase('longSetup') as SubingResearchResponse
  payload.companion = { status: 'insufficient_data', snapshot: null }
  const result = normalizeSubingResearch(payload)

  assert.equal(result.companion?.status, 'insufficient_data')
  assert.equal(result.companion?.snapshot, null)
})

test('supports only the three SuBing V1 snapshot frequencies', () => {
  assert.equal(isSubingSupportedFrequency('5m'), true)
  assert.equal(isSubingSupportedFrequency('15m'), true)
  assert.equal(isSubingSupportedFrequency('1d'), true)
  assert.equal(isSubingSupportedFrequency('30m'), false)
})

test('maps every formal Signal status without trading or zero-band language', () => {
  assert.equal(subingSignalLabel({ status: 'matched', direction: 'long' }), '买入信号')
  assert.equal(subingSignalLabel({ status: 'matched', direction: 'short' }), '卖出信号')
  assert.equal(subingSignalLabel({ status: 'not_matched', direction: 'none' }), '当前不匹配')
  assert.equal(
    subingSignalLabel({ status: 'insufficient_data', direction: 'none' }),
    '指标 warm-up 中 / 数据不足',
  )
  assert.equal(
    subingSignalLabel({ status: 'research_pending', direction: 'none' }),
    '研究参数/能力待冻结',
  )
  assert.equal(subingSignalLabel({ status: 'matched', direction: 'none' }), '当前不匹配')
  for (const label of ['买入信号', '卖出信号', '当前不匹配', '指标 warm-up 中 / 数据不足']) {
    assert.doesNotMatch(label, /零轴|zero|下单|仓位|止损|止盈|提醒/i)
  }
})

test('schedules one bounded refresh only for an older companion at a common 5m boundary', () => {
  const commonBoundary = normalizeSubingResearch(
    cloneSubingLifecycleCase('olderCompanionAtBoundary') as SubingResearchResponse,
  )

  assert.equal(shouldScheduleSubingCompanionRefresh(commonBoundary), true)
  assert.equal(shouldScheduleSubingCompanionRefresh({
    ...commonBoundary,
    companion: { status: 'insufficient_data', snapshot: null },
  }), false)
  assert.equal(shouldScheduleSubingCompanionRefresh({
    ...commonBoundary,
    primary: {
      ...commonBoundary.primary,
      snapshot: { ...commonBoundary.primary.snapshot!, bar_end: commonBoundary.companion!.snapshot!.bar_end },
    },
  }), false)
})

test('SuBing observation composable preserves current dominant identity after extraction', async () => {
  const selectedOverlay = ref<'subing' | 'htdy' | 'none'>('subing')
  const symbol = ref('ag')
  const frequency = ref<'5m' | '15m' | '1d'>('5m')
  const dominants = ref([{
    product: 'ag',
    product_name: '白银',
    sector: 'precious',
    exchange: 'SHFE',
    actual_contract: 'AG2601',
    dominant_mapping_date: '2026-01-12',
  }])
  const replacements: BarData[][] = []
  const controller = useSubingObservation({
    selectedOverlay,
    symbol,
    frequency,
    dominants,
    selectedDominant: computed(() => dominants.value[0]),
    followLatest: ref(true),
    fetchSnapshot: async () => normalizeSubingResearch(readyPayload),
    fetchDominants: async () => ({ items: dominants.value }),
    refreshSeries: async () => true,
    visibleBars: () => [bar('2026-01-12T01:30:00Z', '2026-01-12')],
    replaceChartBars: (items) => replacements.push(items),
  })

  await controller.refresh()

  assert.equal(controller.subing.value?.actual_contract, 'AG2601')
  assert.equal(controller.subingError.value, false)
  assert.equal(controller.subingLoading.value, false)
  assert.equal(replacements.length, 1)
  controller.dispose()
})

function bar(time: string, tradingDay: string): BarData {
  return {
    time,
    trading_day: tradingDay,
    open: 99,
    high: 102,
    low: 98,
    close: 100,
    volume: 1_000,
  }
}
