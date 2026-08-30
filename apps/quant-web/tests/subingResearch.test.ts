import test from 'node:test'
import assert from 'node:assert/strict'
import { computed, ref } from 'vue'
import { useSubingObservation } from '../src/composables/useSubingObservation.ts'
import {
  isSubingSupportedFrequency,
  shouldScheduleSubingCompanionRefresh,
  subingLifecycleStageLabel,
  subingSignalLabel,
  normalizeSubingResearch,
  type SubingResearchResponse,
} from '../src/types/market.ts'
import { lifecycleSnapshotToMarkers } from '../src/utils/subingLifecycleMarkers.ts'
import { buildSubingLifecyclePivotFacts } from '../src/utils/subingLifecycleFacts.ts'
import {
  cloneSubingLifecycleCase,
  reidentifySubingResponse,
} from './fixtures/subingLifecycleCases.mjs'
import { readFileSync } from 'node:fs'

const readyPayload = cloneSubingLifecycleCase('longSetup') as SubingResearchResponse

test('normalizes Decimal Factor values at the SuBing HTTP boundary', () => {
  const result = normalizeSubingResearch(readyPayload)

  assert.equal(result.primary.snapshot?.slope_5_bps_per_bar, 2)
  assert.equal(result.primary.snapshot?.macd_zero_distance_bps, 15)
  assert.equal(result.primary.snapshot?.volume_ratio_prev, 1)
})

test('normalizes the complete additive lifecycle contract without changing Factor values', () => {
  const payload = cloneSubingLifecycleCase('pivotRetest1') as SubingResearchResponse
  const result = normalizeSubingResearch(payload)

  assert.equal(result.primary.snapshot?.slope_5_bps_per_bar, 2)
  assert.equal(result.companion?.status, 'ready')
  assert.equal(
    result.lifecycle.trigger_reference_pivot?.price,
    110,
  )
  assert.equal(result.lifecycle.bound_reference_pivot, null)
  assert.equal(result.lifecycle.rebreak_reference_price, 115)
  assert.equal(result.lifecycle.volume_ratio_prev, 3)
  assert.equal(result.lifecycle.open_interest_delta, 18)
  assert.equal(result.lifecycle.latest_transition?.to_stage, 'setup_armed')
})

test('formats trigger and protective lifecycle pivots as separate current facts', () => {
  const setup = normalizeSubingResearch(
    cloneSubingLifecycleCase('pivotRetest1') as SubingResearchResponse,
  )
  const confirmed = normalizeSubingResearch(
    cloneSubingLifecycleCase('pivotRetestConfirmed') as SubingResearchResponse,
  )

  assert.deepEqual(buildSubingLifecyclePivotFacts(setup.lifecycle), [
    { role: 'trigger', label: '触发前高', price: 110 },
  ])
  assert.deepEqual(buildSubingLifecyclePivotFacts(confirmed.lifecycle), [
    { role: 'trigger', label: '触发前高', price: 110 },
    { role: 'bound', label: '绑定前低', price: 105 },
  ])
})

test('reidentifies both lifecycle pivot roles with the physical contract', () => {
  const response = reidentifySubingResponse(
    cloneSubingLifecycleCase('pivotRetestConfirmed'),
    'AG2602',
  ) as SubingResearchResponse

  assert.equal(response.lifecycle.trigger_reference_pivot?.contract, 'AG2602')
  assert.match(response.lifecycle.trigger_reference_pivot?.pivot_id ?? '', /^AG2602:/)
  assert.equal(response.lifecycle.bound_reference_pivot?.contract, 'AG2602')
  assert.match(response.lifecycle.bound_reference_pivot?.pivot_id ?? '', /^AG2602:/)
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

test('keeps current Lifecycle markers behind the preference without gating Strategy markers', () => {
  const source = readFileSync(new URL('../src/pages/market/chart.vue', import.meta.url), 'utf8')

  assert.match(source, /const lifecycleMarkers = computed\(\(\) => \{\s+if \(!showSubingInternalProcess\.value\) return \[\]/)
  assert.match(source, /const researchMarkers = computed\(\(\) => mergeKlineMarkers\(\s+lifecycleMarkers\.value,\s+visibleHistoricalResearchMarkers\.value,/)
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

test('keeps an insufficient companion explicit without inventing a Factor snapshot', () => {
  const payload = cloneSubingLifecycleCase('longSetup') as SubingResearchResponse
  payload.companion = { status: 'insufficient_data', snapshot: null }
  const result = normalizeSubingResearch(payload)

  assert.equal(result.companion?.status, 'insufficient_data')
  assert.equal(result.companion?.snapshot, null)
})

test('exposes only the 5m and 15m SuBing public observation frequencies', () => {
  assert.equal(isSubingSupportedFrequency('5m'), true)
  assert.equal(isSubingSupportedFrequency('15m'), true)
  assert.equal(isSubingSupportedFrequency('1d'), false)
  assert.equal(isSubingSupportedFrequency('30m'), false)
  assert.equal(isSubingSupportedFrequency('60m'), false)
  assert.equal(isSubingSupportedFrequency('1w'), false)
})

test('does not request the backend SuBing read capability for a public 1d panel', async () => {
  let requests = 0
  const dominants = ref([{
    product: 'ag',
    product_name: '白银',
    sector: 'precious',
    exchange: 'SHFE',
    actual_contract: 'AG2601',
    dominant_mapping_date: '2026-01-12',
  }])
  const controller = useSubingObservation({
    selectedOverlay: ref('subing'),
    symbol: ref('ag'),
    frequency: ref('1d'),
    dominants,
    selectedDominant: computed(() => dominants.value[0]),
    fetchSnapshot: async () => {
      requests += 1
      return normalizeSubingResearch(readyPayload)
    },
    fetchDominants: async () => ({ items: dominants.value }),
    refreshSeries: async () => true,
  })

  await controller.refresh()

  assert.equal(requests, 0)
  assert.equal(controller.subingSupported.value, false)
  assert.equal(controller.subing.value, null)
  controller.dispose()
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

test('SuBing observation composable preserves current dominant identity without owning chart bars', async () => {
  const selectedOverlay = ref<'subing' | 'htdy' | 'none'>('subing')
  const symbol = ref('ag')
  const frequency = ref<'5m' | '15m'>('5m')
  const dominants = ref([{
    product: 'ag',
    product_name: '白银',
    sector: 'precious',
    exchange: 'SHFE',
    actual_contract: 'AG2601',
    dominant_mapping_date: '2026-01-12',
  }])
  const controller = useSubingObservation({
    selectedOverlay,
    symbol,
    frequency,
    dominants,
    selectedDominant: computed(() => dominants.value[0]),
    fetchSnapshot: async () => normalizeSubingResearch(readyPayload),
    fetchDominants: async () => ({ items: dominants.value }),
    refreshSeries: async () => true,
  })

  await controller.refresh()

  assert.equal(controller.subing.value?.actual_contract, 'AG2601')
  assert.equal(controller.subingError.value, false)
  assert.equal(controller.subingLoading.value, false)
  controller.dispose()
})
