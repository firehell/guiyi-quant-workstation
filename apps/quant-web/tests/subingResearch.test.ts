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

const readyPayload = {
  symbol: 'jm',
  product_name: '焦煤',
  frequency: '5m',
  actual_contract: 'JM2609',
  dominant_mapping_date: '2026-08-13',
  segment_start_trading_day: '2026-08-12',
  source_mode: 'canonical_live',
  live_observation: 'available',
  live_reason: null,
  macd_policy_id: 'web_macd_legacy_v1',
  signal_macd_policy_id: 'subing_macd_sma_window_scale2_v1',
  calibration_state: 'accepted',
  calibration_id: 'subing_intraday_v1',
  primary: {
    status: 'ready',
    snapshot: {
      timeframe: '5m',
      bar_end: '2026-08-13T02:25:00Z',
      trading_day: '2026-08-13',
      contract: 'JM2609',
      segment_start_trading_day: '2026-08-12',
      bar_source: 'live',
      close: '100.5',
      ema21: '99.5',
      price_side: 'above',
      slope_5_raw: '0.12',
      slope_10_raw: '0.08',
      slope_5_bps_per_bar: '2.7',
      slope_10_bps_per_bar: '1.8',
      macd_dif: '0.7',
      macd_dea: '0.5',
      macd_histogram: '0.4',
      macd_cross: 'golden',
      macd_cross_level: '0.6',
      macd_zero_distance_abs: '0.6',
      macd_zero_distance_bps: '59.7',
      volume: '342',
      previous_volume: '100',
      volume_ratio_prev: '3.42',
    },
  },
  companion: {
    status: 'insufficient_data',
    snapshot: null,
  },
  primary_signal: {
    status: 'matched', direction: 'long', trigger_timeframe: '5m',
    lower_tf_confirmation: false, resolution: null,
    conditions: [{ code: 'PRIMARY_MACD_CROSS', state: 'pass' }], error_code: null,
  },
  resolved_signal: null,
  lifecycle: {
    formula_version: 'subing_lifecycle_v2', policy_id: 'subing_lifecycle_v2_research_v1', research_only: true,
    observed_at: '2026-08-13T02:25:00Z', anchor_bar_end: '2026-08-13T02:15:00Z',
    availability: 'ready', unavailable_reason: null, direction: 'none', stage: 'idle',
    opportunity_key: null, entry_progress: null, trigger_kind: null, trigger_timeframe: null,
    triggered_at: null, confirmation_source: null, confirmed_at: null, hold_count: 0, hold_required: 3,
    bound_reference_pivot: null, rebreak_reference_price: null, retest_at: null, retest_rebreak_count: 0,
    volume_ratio_prev: null, open_interest_delta: null, current_risk_codes: [], risk_progress: null,
    lower_tf_risk_count: 0, last_confirmed_stage: 'idle', last_confirmed_at: null, latest_transition: null,
    crossed_trading_day: false, boundary_reset: null, formal_v1_matched: false,
  },
} as unknown as SubingResearchResponse

test('normalizes Decimal Factor values at the SuBing HTTP boundary', () => {
  const result = normalizeSubingResearch(readyPayload)

  assert.equal(result.primary.snapshot?.slope_5_bps_per_bar, 2.7)
  assert.equal(result.primary.snapshot?.macd_zero_distance_bps, 59.7)
  assert.equal(result.primary.snapshot?.volume_ratio_prev, 3.42)
})

test('normalizes the complete additive lifecycle contract without changing Factor values', () => {
  const result = normalizeSubingResearch({
    ...readyPayload,
    lifecycle: {
      formula_version: 'subing_lifecycle_v2', policy_id: 'subing_lifecycle_v2_research_v1', research_only: true,
      observed_at: '2026-08-13T02:25:00Z', anchor_bar_end: '2026-08-13T02:15:00Z',
      availability: 'ready', unavailable_reason: null, direction: 'long', stage: 'entry_confirmed',
      opportunity_key: 'subing_lifecycle_v2_research_v1:JM:JM2609:2026-08-12:long:2026-08-13T02:00:00Z',
      entry_progress: null, trigger_kind: 'pivot_break', trigger_timeframe: '15m',
      triggered_at: '2026-08-13T02:15:00Z', confirmation_source: 'pivot_break_hold',
      confirmed_at: '2026-08-13T02:25:00Z', hold_count: 3, hold_required: 3,
      bound_reference_pivot: {
        pivot_id: 'pivot:high:2026-08-13T01:45:00Z', kind: 'high', timeframe: '15m',
        pivot_time: '2026-08-13T01:45:00Z', confirmed_at: '2026-08-13T02:15:00Z',
        price: '104.5', contract: 'JM2609', segment_start_trading_day: '2026-08-12',
      },
      rebreak_reference_price: '104.5', retest_at: null, retest_rebreak_count: 0,
      volume_ratio_prev: '3.42', open_interest_delta: '-12.5', current_risk_codes: [],
      risk_progress: null, lower_tf_risk_count: 0, last_confirmed_stage: 'entry_confirmed',
      last_confirmed_at: '2026-08-13T02:25:00Z', latest_transition: {
        transition_id: 'transition:entry', transition_at: '2026-08-13T02:25:00Z',
        from_stage: 'setup_armed', to_stage: 'entry_confirmed', reason_codes: ['PIVOT_BREAK_HOLD'],
      },
      crossed_trading_day: false, boundary_reset: null, formal_v1_matched: false,
    },
  } as SubingResearchResponse)

  assert.equal(result.primary.snapshot?.slope_5_bps_per_bar, 2.7)
  assert.equal(result.lifecycle.bound_reference_pivot?.price, 104.5)
  assert.equal(result.lifecycle.rebreak_reference_price, 104.5)
  assert.equal(result.lifecycle.volume_ratio_prev, 3.42)
  assert.equal(result.lifecycle.open_interest_delta, -12.5)
  assert.equal(result.lifecycle.latest_transition?.to_stage, 'entry_confirmed')
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
  const lifecycle = normalizeSubingResearch({
    ...readyPayload,
    lifecycle: {
      formula_version: 'subing_lifecycle_v2', policy_id: 'subing_lifecycle_v2_research_v1', research_only: true,
      observed_at: '2026-08-13T02:25:00Z', anchor_bar_end: '2026-08-13T02:15:00Z',
      availability: 'ready', unavailable_reason: null, direction: 'long', stage: 'exit_risk',
      opportunity_key: 'key', entry_progress: null, trigger_kind: 'pivot_break', trigger_timeframe: '15m',
      triggered_at: '2026-08-13T02:15:00Z', confirmation_source: 'pivot_break_hold',
      confirmed_at: '2026-08-13T02:25:00Z', hold_count: 3, hold_required: 3,
      bound_reference_pivot: null, rebreak_reference_price: null, retest_at: null, retest_rebreak_count: 0,
      volume_ratio_prev: null, open_interest_delta: null, current_risk_codes: ['LOWER_TF_EMA21_BREACH'],
      risk_progress: '2/2', lower_tf_risk_count: 2, last_confirmed_stage: 'entry_confirmed',
      last_confirmed_at: '2026-08-13T02:25:00Z', latest_transition: {
        transition_id: 'transition:risk', transition_at: '2026-08-13T02:30:00Z',
        from_stage: 'continuation', to_stage: 'exit_risk', reason_codes: ['LOWER_TF_EMA21_BREACH'],
      },
      crossed_trading_day: false, boundary_reset: null, formal_v1_matched: false,
    },
  } as SubingResearchResponse).lifecycle

  assert.deepEqual(lifecycleSnapshotToMarkers(lifecycle), [
    { id: 'lifecycle:key:pivot-break', time: '2026-08-13T02:15:00Z', label: '前高突破', tooltip: 'SuBing 生命周期研究 · 前高突破', tone: 'neutral', position: 'belowBar', shape: 'circle' },
    { id: 'lifecycle:key:entry', time: '2026-08-13T02:25:00Z', label: '研究确认', tooltip: 'SuBing 生命周期研究 · 研究确认', tone: 'neutral', position: 'belowBar', shape: 'circle' },
    { id: 'lifecycle:key:exit-risk', time: '2026-08-13T02:30:00Z', label: '风险', tooltip: 'SuBing 生命周期研究 · 风险', tone: 'neutral', position: 'belowBar', shape: 'circle' },
  ])
})

test('maps a closed lifecycle only to its immutable close marker', () => {
  const markers = lifecycleSnapshotToMarkers({
    formula_version: 'subing_lifecycle_v2', policy_id: 'subing_lifecycle_v2_research_v1', research_only: true,
    observed_at: '2026-08-13T02:30:00Z', anchor_bar_end: '2026-08-13T02:30:00Z',
    availability: 'ready', unavailable_reason: null, direction: 'short', stage: 'closed', opportunity_key: 'key',
    entry_progress: null, trigger_kind: null, trigger_timeframe: null, triggered_at: null,
    confirmation_source: null, confirmed_at: null, hold_count: 0, hold_required: 3,
    bound_reference_pivot: null, rebreak_reference_price: null, retest_at: null, retest_rebreak_count: 0,
    volume_ratio_prev: null, open_interest_delta: null, current_risk_codes: [], risk_progress: null,
    lower_tf_risk_count: 0, last_confirmed_stage: 'closed', last_confirmed_at: null,
    latest_transition: { transition_id: 'transition:closed', transition_at: '2026-08-13T02:30:00Z', from_stage: 'setup_armed', to_stage: 'closed', reason_codes: ['FORMAL_V1'] },
    crossed_trading_day: false, boundary_reset: null, formal_v1_matched: false,
  })

  assert.deepEqual(markers, [{
    id: 'lifecycle:key:closed', time: '2026-08-13T02:30:00Z', label: '结束',
    tooltip: 'SuBing 生命周期研究 · 结束', tone: 'neutral', position: 'belowBar', shape: 'circle',
  }])
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
  const result = normalizeSubingResearch(readyPayload)

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
  const commonBoundary = normalizeSubingResearch({
    ...readyPayload,
    primary: {
      ...readyPayload.primary,
      snapshot: {
        ...readyPayload.primary.snapshot!,
        bar_end: '2026-08-13T02:30:00Z',
      },
    },
    companion: {
      status: 'ready',
      snapshot: {
        ...readyPayload.primary.snapshot!,
        timeframe: '15m',
        bar_end: '2026-08-13T02:15:00Z',
      },
    },
  })

  assert.equal(shouldScheduleSubingCompanionRefresh(commonBoundary), true)
  assert.equal(shouldScheduleSubingCompanionRefresh({
    ...commonBoundary,
    companion: { status: 'insufficient_data', snapshot: null },
  }), false)
  assert.equal(shouldScheduleSubingCompanionRefresh({
    ...commonBoundary,
    primary: {
      ...commonBoundary.primary,
      snapshot: { ...commonBoundary.primary.snapshot!, bar_end: '2026-08-13T02:25:00Z' },
    },
  }), false)
})

test('SuBing observation composable preserves current dominant identity after extraction', async () => {
  const selectedOverlay = ref<'subing' | 'htdy' | 'none'>('subing')
  const symbol = ref('jm')
  const frequency = ref<'5m' | '15m' | '1d'>('5m')
  const dominants = ref([{
    product: 'jm',
    product_name: '焦煤',
    sector: 'black',
    exchange: 'DCE',
    actual_contract: 'JM2609',
    dominant_mapping_date: '2026-08-13',
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
    visibleBars: () => [bar('2026-08-13T02:25:00Z', '2026-08-13')],
    replaceChartBars: (items) => replacements.push(items),
  })

  await controller.refresh()

  assert.equal(controller.subing.value?.actual_contract, 'JM2609')
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
