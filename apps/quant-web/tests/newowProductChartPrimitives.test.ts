import assert from 'node:assert/strict'
import * as primitives from '../src/components/market/detail/newow/newowProductChartPrimitives.ts'
import test from 'node:test'

import {
  buildNewowAuxiliaryChartModel,
  buildNewowAuxiliaryDisclosure,
  buildNewowProductChartModel,
  chartMarkerTime,
  classifyNewowHintTone,
  preserveNewowViewport,
  buildNewowActionCallouts,
  resolveNewowAuxiliaryRenderState,
} from '../src/components/market/detail/newow/newowProductChartPrimitives.ts'
import { formatDecimalText } from '../src/utils/marketDisplay.ts'
import type {
  NewowAuxiliaryValue,
  NewowProductFrequency,
  NewowProductSectionResponse,
  NewowProductStrategy,
} from '../src/types/newowProduct.ts'

test('projects each server-owned main layer for all nine strategy-period identities', () => {
  const expected = {
    trend: [['b', 'B'], ['a', 'A']],
    oscillation: [['upper', 'HHV'], ['lower', 'LLV']],
    main_rise: [['ma35', 'MA35'], ['ma45', 'MA45']],
  } as const

  for (const strategy of ['trend', 'oscillation', 'main_rise'] as const) {
    for (const frequency of ['1w', '1d', '60m'] as const) {
      const model = buildNewowProductChartModel(chartResponse(strategy, frequency))
      assert.deepEqual(model.identity, { product: 'jm', strategy, frequency })
      assert.deepEqual(model.mainLines.map(({ key, label }) => [key, label]), expected[strategy])
      assert.deepEqual(model.mainLines.map((line) => line.points.map((point) => point.value)), [[101, 102], [99, 100]])
      assert.equal(model.mainLines.every((line) => line.segmentId === 'segment-1'), true)
    }
  }
})

test('does not connect a main line across a price-gap calculation segment', () => {
  const response = chartResponse('trend', '1d')
  response.value!.bars[1] = {
    ...response.value!.bars[1]!,
    calculation_segment_id: 'segment-1|price-gap:2026-08-15T00:00:00Z',
  }
  const model = buildNewowProductChartModel(response)
  assert.equal(model.mainLines.length, 4)
  assert.equal(model.mainLines.every((line) => line.points.length === 1), true)
})

test('preserves initial-clear eligibility into the marker label and detail model', () => {
  const response = chartResponse('main_rise', '1d')
  const value = response.value!
  const source = value.bars[1]!
  value.actions.push({
    signal_id: 'initial-clear', kind: 'CLEAR', bar_end: source.bar_end,
    trading_day: source.trading_day, reference_price: '100',
    physical_contract: source.physical_contract, segment_id: source.segment_id,
    related_build_id: null, trade_eligibility: 'INITIAL_CLEAR_NO_ENTRY', sequence: 0,
  } as any)
  value.frames[1]!.action_ids = ['initial-clear']
  value.frames[1]!.main_state = 'CLEAR'

  const model = buildNewowProductChartModel(response)
  const action = model.actions[0]!
  assert.equal(action.tradeEligibility, 'INITIAL_CLEAR_NO_ENTRY')
  assert.equal(
    primitives.productChartMarker(action, null, { year: 2026, month: 8, day: 15 }).text,
    '清仓（无入场）',
  )
  assert.equal(buildNewowActionCallouts(model)[0]?.title, '清仓（无入场）')
  assert.deepEqual(primitives.describeNewowProductAction(action), {
    label: '清仓（无入场）',
    explanation: '初始无入场：未观察到可配对 BUILD，不生成参考交易。',
  })
  assert.equal(
    primitives.newowInitialClearLabel('INITIAL_CLEAR_NO_ENTRY'),
    '清仓（无入场）',
  )
  assert.equal(primitives.newowInitialClearLabel('ELIGIBLE'), null)
})

test('preserves same-Bar CLEAR then BUILD identities and keeps hint anchor separate from action reference price', () => {
  const response = chartResponse('oscillation', '60m')
  const value = response.value!
  const barEnd = value.bars[1]!.bar_end
  const owner = {
    trading_day: value.bars[1]!.trading_day,
    physical_contract: value.bars[1]!.physical_contract,
    segment_id: value.bars[1]!.segment_id,
  }
  value.actions = [
    { signal_id: 'clear-stable', kind: 'CLEAR', bar_end: barEnd, ...owner, reference_price: '109.25', related_build_id: 'prior-build', trade_eligibility: 'ELIGIBLE', sequence: 0 },
    { signal_id: 'build-stable', kind: 'BUILD', bar_end: barEnd, ...owner, reference_price: '91.75', related_build_id: null, trade_eligibility: 'ELIGIBLE', sequence: 1 },
  ]
  value.hints = [{
    hint_id: 'hint-stable', kind: 'D4', bar_end: barEnd, known_at: '2026-08-15T08:30:00Z',
    anchor_price: '88.125', physical_contract: owner.physical_contract, segment_id: owner.segment_id,
    retrospective: false, quantity_effect: 'none', sequence: 2,
  }]

  const model = buildNewowProductChartModel(response)

  assert.deepEqual(model.actions.map(({ id, kind, sequence }) => ({ id, kind, sequence })), [
    { id: 'clear-stable', kind: 'CLEAR', sequence: 0 },
    { id: 'build-stable', kind: 'BUILD', sequence: 1 },
  ])
  assert.deepEqual(model.actions.map(({ referencePrice, value }) => [referencePrice, value]), [
    ['109.25', 109.25], ['91.75', 91.75],
  ])
  assert.deepEqual(buildNewowActionCallouts(model).map(callout => callout.detail), [
    '参考价 109', '参考价 92',
  ])
  assert.deepEqual(model.hints.map(({ anchorPrice, value, confirmedAt, sourceIdentity, formulaVersions, physicalContract, segmentId }) => ({
    anchorPrice, value, confirmedAt, sourceIdentity, formulaVersions, physicalContract, segmentId,
  })), [{
    anchorPrice: '88.125', value: 88.125, confirmedAt: '2026-08-15T08:30:00Z',
    sourceIdentity: 'canonical:jm:JM2601',
    formulaVersions: ['newow_hhv_llv_channel_page_v1', 'newow_oscillation_hhv_llv10_page_v1'],
    physicalContract: 'JM2601', segmentId: 'segment-1',
  }])
  assert.notEqual(model.hints[0]!.value, model.actions[1]!.value)
})

test('splits server values at physical owner boundaries instead of connecting contracts', () => {
  const response = chartResponse('main_rise', '1d')
  const value = response.value!
  value.bars[1] = { ...value.bars[1]!, physical_contract: 'JM2605', segment_id: 'segment-2', calculation_segment_id: 'segment-2' }

  const model = buildNewowProductChartModel(response)

  assert.deepEqual(model.mainLines.map(({ key, segmentId, points }) => [key, segmentId, points.length]), [
    ['ma35', 'segment-1', 1], ['ma35', 'segment-2', 1],
    ['ma45', 'segment-1', 1], ['ma45', 'segment-2', 1],
  ])
})

test('states auxiliary applicability and evidence without turning unavailable into no signal', () => {
  const mirror = buildNewowAuxiliaryDisclosure('zhaoyao_mirror', '60m', 'ready')
  assert.equal(mirror.applicability, 'ready')
  assert.match(mirror.disclosure, /回看/)
  assert.match(mirror.disclosure, /会重绘/)

  const dailyCup = buildNewowAuxiliaryDisclosure('cup_handle', '1d', 'warming')
  assert.equal(dailyCup.applicability, 'warming')
  assert.match(dailyCup.disclosure, /clean-room/i)
  assert.match(dailyCup.disclosure, /确认时间/)

  for (const frequency of ['1w', '60m'] as const) {
    const cup = buildNewowAuxiliaryDisclosure('cup_handle', frequency, 'unavailable')
    assert.equal(cup.applicability, 'not_applicable')
    assert.match(cup.disclosure, /不适用/)
    assert.doesNotMatch(cup.disclosure, /暂无信号/)
  }

  const energy = buildNewowAuxiliaryDisclosure('up_down_energy', '1w', 'unavailable')
  assert.equal(energy.applicability, 'unavailable')
  assert.match(energy.disclosure, /不可用/)
})

test('uses authoritative trading_day for daily and weekly chart coordinates', () => {
  assert.deepEqual(chartMarkerTime('2026-08-14T23:00:00Z', '1d', '2026-08-15'), {
    year: 2026, month: 8, day: 15,
  })
  assert.equal(chartMarkerTime('2026-08-14T23:00:00Z', '60m', '2026-08-15'), 1786748400)
})

test('projects each auxiliary server sequence without recomputing its values', () => {
  const control = buildNewowAuxiliaryChartModel(auxiliaryValue('main_force_control', {
    kongpan: [1.25, -2.5], status: ['control', 'weak'], current_status: 'weak',
    formula_version: 'newow_main_force_control_page_v1',
  }))
  assert.deepEqual(control.series.map((series) => [series.key, series.label, series.points.map((point) => point.value)]), [
    ['kongpan', '主力控盘', [1.25, -2.5]],
  ])

  const energy = buildNewowAuxiliaryChartModel(auxiliaryValue('up_down_energy', {
    var4: [null, 3], ma10: [1, 2], band_entry: [0, 1], rebound_entry: [1, 0], oversold_entry: [0, 0],
    var3: [5, 6], ma120: [4, 4], formula_version: 'newow_up_down_energy_page_v1',
  }))
  assert.deepEqual(energy.series.map((series) => series.key), [
    'var4', 'ma10', 'band_entry', 'rebound_entry', 'oversold_entry', 'var3', 'ma120',
  ])
  assert.deepEqual(energy.series[0]!.points.map((point) => [point.barEnd, point.value]), [
    ['2026-08-15T07:00:00Z', 3],
  ])

  const mirror = buildNewowAuxiliaryChartModel(auxiliaryValue('zhaoyao_mirror', {
    entry: [1, 0], wash: [2, 0], distribution: [3, 0], markup: [4, 0], exit: [5, 0],
    inducement: [6, 0], peaks: [7, 0], caution: [8, 0], repainting: true,
    formal_signal_eligible: false, formula_version: 'newow_zhaoyao_mirror_repainting_page_v1',
  }))
  assert.deepEqual(mirror.series.map((series) => series.key), [
    'entry', 'wash', 'distribution', 'markup', 'exit', 'inducement', 'peaks', 'caution',
  ])
  assert.equal(mirror.series.every((series) => series.points[0]!.segmentId === 'segment-1'), true)
})

test('prioritizes refresh and stale/error state over a retained auxiliary value', () => {
  assert.deepEqual(resolveNewowAuxiliaryRenderState('loading', true, null), {
    mode: 'loading', showRetainedValue: true,
    message: '正在刷新；以下为上次成功的预览。',
  })
  assert.deepEqual(resolveNewowAuxiliaryRenderState('stale', true, 'NEWOW_API_UNAVAILABLE'), {
    mode: 'stale', showRetainedValue: true,
    message: '刷新失败（NEWOW_API_UNAVAILABLE）；以下为上次成功的 stale 预览。',
  })
  assert.deepEqual(resolveNewowAuxiliaryRenderState('unavailable', false, 'NEWOW_API_UNAVAILABLE'), {
    mode: 'error', showRetainedValue: false,
    message: '加载失败（NEWOW_API_UNAVAILABLE）。',
  })
})

function auxiliaryValue(
  component: Exclude<NewowAuxiliaryValue['component'], 'cup_handle'>,
  data: NewowAuxiliaryValue['segments'][number]['data'],
): NewowAuxiliaryValue {
  return {
    component, formula_version: data !== null && !Array.isArray(data) ? data.formula_version : 'test',
    segments: [{
      physical_contract: 'JM2601', segment_id: 'segment-1',
      bar_ends: ['2026-08-14T07:00:00Z', '2026-08-15T07:00:00Z'],
      status: { status: 'ready', evidence_status: 'ACTIVE_CODE_VERIFIED', reason_code: null }, data,
    }],
    repainting: component === 'zhaoyao_mirror', formal_signal_eligible: false,
    page_parity: component !== 'cup_handle', source_category: 'guiyi_product_auxiliary_adapter',
    allowed_uses: ['product_auxiliary'],
  }
}

function chartResponse(
  strategy: NewowProductStrategy,
  frequency: NewowProductFrequency,
): MutableChartResponse {
  const keys = strategy === 'trend' ? ['b', 'a']
    : strategy === 'oscillation' ? ['upper', 'lower'] : ['ma35', 'ma45']
  const formulas = strategy === 'trend'
    ? ['newow_escape_d123_page_v2', 'newow_trend_band_page_v2']
    : strategy === 'oscillation'
      ? ['newow_hhv_llv_channel_page_v1', 'newow_oscillation_hhv_llv10_page_v1']
      : ['newow_buy_d456_page_v1', 'newow_escape_d123_page_v2', 'newow_magic11_page_v1', 'newow_main_rise_j_reduce_page_v1', 'newow_main_rise_ma35_ma45_page_v1']
  const bars = [
    bar('2026-08-14T07:00:00Z', '2026-08-14', '100'),
    bar('2026-08-15T07:00:00Z', '2026-08-15', '101'),
  ]
  return {
    meta: {
      schema_version: 'newow_product_detail_v3',
      identity: { product: 'jm', strategy, frequency, series_kind: 'actual_dominant', profile_id: `newow_product_${strategy}_${frequency}_v1`, formula_versions: formulas },
      as_of: '2026-08-15T09:00:00Z', read_at: '2026-08-15T09:00:01Z', input_content_sha256: 'a'.repeat(64),
      data_revision_identity: null, snapshot_token: 'snapshot-a', reference_model_version: 'newow_marker_reference_zero_cost_v3',
      futures_adaptation_version: 'newow_futures_quality_segment_v3',
    },
    section: 'chart',
    status: { status: 'ready', evidence_status: 'ACTIVE_CODE_VERIFIED', reason_code: null },
    value: {
      chart_from: '2026-08-14', chart_through: '2026-08-15', page_identity: 'b'.repeat(64), price_unavailable_days: [], bars,
      frames: bars.map((item, index) => ({
        bar_end: item.bar_end, main_state: index === 0 ? 'FLAT' : 'HOLD',
        main_values: { [keys[0]!]: index === 0 ? '101' : '102', [keys[1]!]: index === 0 ? '99' : '100' },
        status: { status: 'ready', evidence_status: 'ACTIVE_CODE_VERIFIED', reason_code: null }, action_ids: [], hint_ids: [],
      })),
      actions: [], hints: [], diagnostics: [], next_before: null, repainting: false, formal_signal_eligible: true,
      allowed_uses: ['product_chart', 'reference_input'],
    },
  } as MutableChartResponse
}

function bar(barEnd: string, tradingDay: string, close: string) {
  return {
    bar_end: barEnd, trading_day: tradingDay, open: close, high: '110', low: '90', close,
    volume: 10, open_interest: 20, physical_contract: 'JM2601', segment_id: 'segment-1', calculation_segment_id: 'segment-1',
    source_identity: 'canonical:jm:JM2601', observation_eligible: true, completed: true as const,
  }
}

type MutableChartResponse = {
  -readonly [K in keyof NewowProductSectionResponse<'chart'>]: NewowProductSectionResponse<'chart'>[K] extends object
    ? Mutable<NewowProductSectionResponse<'chart'>[K]>
    : NewowProductSectionResponse<'chart'>[K]
}
type Mutable<T> = { -readonly [K in keyof T]: T[K] extends readonly (infer U)[] ? Mutable<U>[] : T[K] extends object ? Mutable<T[K]> : T[K] }


test('trend columns keep valid isolated Bars and omit missing or warming facts', () => {
  const response = chartResponse('trend', '60m')
  const value = response.value!
  const third = bar('2026-08-16T07:00:00Z', '2026-08-16', '102')
  value.bars.push(third)
  value.frames.push({ ...structuredClone(value.frames[1]!), bar_end: third.bar_end })
  value.frames[1]!.main_values.a = null
  let model = buildNewowProductChartModel(response)
  assert.deepEqual(model.mainLines.filter(line => line.key === 'a').map(line => line.points.length), [1, 1])
  assert.deepEqual(model.bandAreas.map(area => area.time), [
    chartMarkerTime(value.bars[0]!.bar_end, '60m', value.bars[0]!.trading_day),
    chartMarkerTime(value.bars[2]!.bar_end, '60m', value.bars[2]!.trading_day),
  ])
  value.frames.splice(1, 1)
  model = buildNewowProductChartModel(response)
  assert.deepEqual(model.mainLines.filter(line => line.key === 'b').map(line => line.points.length), [1, 1])
  value.frames[1]!.status.status = 'warming'
  model = buildNewowProductChartModel(response)
  assert.equal(model.mainLines.filter(line => line.key === 'b').length, 1)
  assert.deepEqual(model.bandAreas.map(area => area.time), [
    chartMarkerTime(value.bars[0]!.bar_end, '60m', value.bars[0]!.trading_day),
  ])
})

test('MACD uses point times, preserves signed zero and splits invalid or warming points', () => {
  const times = ['2026-08-14T07:00:00Z', '2026-08-15T07:00:00Z', '2026-08-16T07:00:00Z']
  const points = times.map((bar_end, index) => ({ bar_end, value: index - 1, ready: index !== 1, valid: true, reason: index === 1 ? 'WARMING' : null }))
  const value = { component: 'macd', segments: [{ physical_contract: 'JM2601', segment_id: 'segment-1', bar_ends: times, data: { dif: points, dea: points, histogram: points.map(point => ({ ...point, ready: true, reason: null })) } }] } as NewowAuxiliaryValue
  const model = buildNewowAuxiliaryChartModel(value)
  assert.deepEqual(model.series.filter(series => series.key === 'dif').map(series => series.points.map(point => point.value)), [[-1], [1]])
  assert.deepEqual(model.series.find(series => series.key === 'histogram')!.points.map(point => point.value), [-1, 0, 1])
})

test('aligns auxiliary by chart owner and exact time, never auxiliary array index or snapshot mismatch', () => {
  assert.equal(typeof primitives.alignNewowAuxiliaryChartModel, 'function')
  const { alignNewowAuxiliaryChartModel, newowChartSnapshotKey } = primitives
  const chart = chartResponse('trend', '1w')
  const value = auxiliaryValue('main_force_control', { kongpan: [20, 30], status: [], current_status: 'weak', formula_version: 'test' })
  const auxiliary = { meta: { ...chart.meta, input_content_sha256: 'c'.repeat(64) }, section: 'auxiliary', status: chart.status, value } as NewowProductSectionResponse<'auxiliary'>
  let aligned = alignNewowAuxiliaryChartModel(chart, auxiliary)
  assert.deepEqual(aligned!.series[0]!.points.map(point => point.time), [{ year: 2026, month: 8, day: 14 }, { year: 2026, month: 8, day: 15 }])
  assert.equal(newowChartSnapshotKey(chart), newowChartSnapshotKey(auxiliary))
  chart.value!.bars[0]!.physical_contract = 'JM2605'
  aligned = alignNewowAuxiliaryChartModel(chart, auxiliary)
  assert.deepEqual(aligned!.series[0]!.points.map(point => point.value), [30])
  assert.equal(alignNewowAuxiliaryChartModel(chart, { ...auxiliary, meta: { ...auxiliary.meta, snapshot_token: 'other' } }), null)
  assert.equal(alignNewowAuxiliaryChartModel(chart, { ...auxiliary, meta: { ...auxiliary.meta, snapshot_token: null } }), null)
})


test('trend model projects one 35%-opacity column per ready Bar with its own state', () => {
  const response = chartResponse('trend', '1d')
  const model = buildNewowProductChartModel(response)

  assert.deepEqual(model.bandAreas, [
    {
      time: { year: 2026, month: 8, day: 14 },
      a: 99,
      b: 101,
      color: 'rgba(54, 90, 245, 0.35)',
    },
    {
      time: { year: 2026, month: 8, day: 15 },
      a: 100,
      b: 102,
      color: 'rgba(245, 183, 38, 0.35)',
    },
  ])

  response.value!.bars.splice(1, 1)
  response.value!.frames.splice(1, 1)
  assert.equal(buildNewowProductChartModel(response).bandAreas.length, 1, 'an isolated valid Bar remains visible')
})

test('trend model projects only ready channel facts at their real prices', () => {
  const response = chartResponse('trend', '1d')
  const value = response.value!
  ;(value as any).trend_channel = {
    kind: 'trend_channel', period: 10, formula_version: 'newow_hhv_llv_channel_page_v1',
    points: value.bars.map((bar, index) => ({
      bar_end: bar.bar_end,
      upper: index === 0 ? '110.25' : null,
      lower: index === 0 ? '89.75' : null,
      formula_version: 'newow_hhv_llv_channel_page_v1',
      status: index === 0
        ? { status: 'ready', evidence_status: 'ACTIVE_CODE_VERIFIED', reason_code: null }
        : { status: 'unavailable', evidence_status: 'ACTIVE_CODE_VERIFIED', reason_code: 'NEWOW_TREND_CHANNEL_BAR_MISSING' },
      physical_contract: bar.physical_contract,
      segment_id: bar.segment_id,
      source_identity: bar.source_identity,
    })),
  }

  const model = buildNewowProductChartModel(response)

  assert.deepEqual((model as any).channelPoints, [{
    barEnd: value.bars[0]!.bar_end,
    tradingDay: value.bars[0]!.trading_day,
    upper: 110.25,
    lower: 89.75,
  }])

  const nonTrend = chartResponse('oscillation', '1d')
  assert.deepEqual((buildNewowProductChartModel(nonTrend) as any).channelPoints, [{
    barEnd: nonTrend.value!.bars[0]!.bar_end,
    tradingDay: nonTrend.value!.bars[0]!.trading_day,
    upper: 101,
    lower: 99,
  }, {
    barEnd: nonTrend.value!.bars[1]!.bar_end,
    tradingDay: nonTrend.value!.bars[1]!.trading_day,
    upper: 102,
    lower: 100,
  }])
})

test('strategy overlays stay mutually exclusive and preserve only their own server values', () => {
  const trend = buildNewowProductChartModel(chartResponse('trend', '1d'))
  assert.equal(trend.bandAreas.length, 2)
  assert.deepEqual(trend.channelPoints, [])

  const oscillationResponse = chartResponse('oscillation', '1d')
  oscillationResponse.value!.frames[1]!.status.status = 'warming'
  const oscillation = buildNewowProductChartModel(oscillationResponse)
  assert.deepEqual(oscillation.bandAreas, [])
  assert.deepEqual(oscillation.channelPoints, [{
    barEnd: oscillationResponse.value!.bars[0]!.bar_end,
    tradingDay: oscillationResponse.value!.bars[0]!.trading_day,
    upper: 101,
    lower: 99,
  }])

  const mainRise = buildNewowProductChartModel(chartResponse('main_rise', '1d'))
  assert.deepEqual(mainRise.channelPoints, [])
  assert.deepEqual(mainRise.bandAreas.map(({ a, b, color }) => ({ a, b, color })), [
    { a: 101, b: 99, color: 'rgba(54, 90, 245, 0.35)' },
    { a: 102, b: 100, color: 'rgba(245, 183, 38, 0.35)' },
  ])
})

test('classifies real hint kinds for display without changing their identities or anchors', () => {
  assert.equal(classifyNewowHintTone('J'), 'risk')
  assert.equal(classifyNewowHintTone('NEWOW_ESCAPE_D2'), 'risk')
  assert.equal(classifyNewowHintTone('D4'), 'entry')
  assert.equal(classifyNewowHintTone('D6'), 'entry')
  assert.equal(classifyNewowHintTone('MAGIC11:7'), 'cycle')
  assert.equal(classifyNewowHintTone('UNKNOWN_SERVER_KIND'), 'neutral')
})

test('projects action labels from exact server reference prices without deriving returns', () => {
  const response = chartResponse('oscillation', '1d')
  const model = buildNewowProductChartModel(response)
  assert.deepEqual(buildNewowActionCallouts(model), model.actions.map(action => ({
    id: action.id,
    time: action.barEnd,
    physicalContract: action.physicalContract,
    price: action.referencePrice,
    title: action.kind === 'BUILD' ? '建仓' : '清仓',
    detail: `参考价 ${formatDecimalText(action.referencePrice, { maximumFractionDigits: 0 })}`,
    tone: action.kind === 'BUILD' ? 'gain' : 'loss',
    above: action.kind === 'CLEAR',
  })))
})

test('preserves Newow viewport only for compatible product frequency and time axes', () => {
  const before = buildNewowProductChartModel(chartResponse('trend', '60m'))
  const compatible = buildNewowProductChartModel(chartResponse('oscillation', '60m'))
  assert.equal(preserveNewowViewport(before, compatible), true)

  compatible.identity.product = 'rb'
  assert.equal(preserveNewowViewport(before, compatible), false)
  compatible.identity.product = 'jm'
  compatible.bars[0]!.barEnd = '2026-08-13T07:00:00Z'
  assert.equal(preserveNewowViewport(before, compatible), false)
})

test('band primitive paints centered per-Bar rectangles that scale with bar spacing and releases attachment', async () => {
  const { NewowProductBandPrimitive } = await import('../src/components/market/detail/newow/newowProductBandPrimitive.ts')
  const model = buildNewowProductChartModel(chartResponse('trend', '1d'))
  assert.equal(model.bandAreas.length, 2)
  const primitive = new NewowProductBandPrimitive()
  const coordinates: unknown[] = []
  const rectangles: number[][] = []
  const colors: string[] = []
  let barSpacing = 10
  let updates = 0
  const context = {
    save() {}, restore() {},
    set fillStyle(value: string) { colors.push(value) },
    fillRect(x: number, y: number, width: number, height: number) { rectangles.push([x, y, width, height]) },
  }
  const target = { useMediaCoordinateSpace(callback: (scope: { context: object }) => void) { callback({ context }) } }
  primitive.attached({ chart: { timeScale: () => ({
    options: () => ({ barSpacing }),
    timeToCoordinate(time: unknown) { coordinates.push(time); return coordinates.length % 2 === 1 ? 10 : 20 },
  }) }, series: { priceToCoordinate: (price: number) => price }, requestUpdate: () => { updates++ } } as never)
  primitive.setData(model.bandAreas)
  primitive.paneViews()[0]!.renderer()!.draw(target as never)
  assert.equal(updates, 1)
  assert.deepEqual(coordinates, [{ year: 2026, month: 8, day: 14 }, { year: 2026, month: 8, day: 15 }])
  assert.deepEqual(rectangles, [[6, 99, 8, 2], [16, 100, 8, 2]])
  assert.deepEqual(colors, ['rgba(54, 90, 245, 0.35)', 'rgba(245, 183, 38, 0.35)'])

  barSpacing = 20
  primitive.paneViews()[0]!.renderer()!.draw(target as never)
  assert.deepEqual(rectangles.slice(2), [[2, 99, 16, 2], [12, 100, 16, 2]])

  barSpacing = 0.5
  primitive.paneViews()[0]!.renderer()!.draw(target as never)
  assert.deepEqual(rectangles.slice(4), [[9.8, 99, 0.4, 2], [19.8, 100, 0.4, 2]])

  primitive.detached(); primitive.setData(model.bandAreas)
  primitive.paneViews()[0]!.renderer()!.draw(target as never)
  assert.equal(updates, 1)
  assert.equal(rectangles.length, 6)
})

test('trend channel primitive paints unconnected price-coordinate dots with fixed colors radius and normal z-order', async () => {
  const { NewowTrendChannelPrimitive } = await import('../src/components/market/detail/newow/newowTrendChannelPrimitive.ts')
  const primitive = new NewowTrendChannelPrimitive()
  const arcs: Array<[number, number, number, string]> = []
  let fill = ''
  let timeScale = 1
  let priceScale = 1
  let updates = 0
  const context = {
    save() {}, restore() {}, beginPath() {}, fill() {},
    set fillStyle(value: string) { fill = value },
    arc(x: number, y: number, radius: number) { arcs.push([x, y, radius, fill]) },
  }
  const target = { useMediaCoordinateSpace(callback: (scope: { context: object }) => void) { callback({ context }) } }
  primitive.attached({
    chart: { timeScale: () => ({ timeToCoordinate: () => 10 * timeScale }) },
    series: { priceToCoordinate: (price: number) => price * priceScale },
    requestUpdate: () => { updates++ },
  } as never)
  primitive.setData([{ time: { year: 2026, month: 8, day: 14 }, upper: 110, lower: 90 }])

  assert.equal(primitive.paneViews()[0]!.zOrder?.(), 'normal')
  primitive.paneViews()[0]!.renderer()!.draw(target as never)
  assert.deepEqual(arcs, [
    [10, 110, 2.5, 'rgba(52, 199, 89, 0.9)'],
    [10, 90, 2.5, 'rgba(255, 59, 48, 0.9)'],
  ])
  assert.equal(updates, 1)

  timeScale = 2; priceScale = 3
  primitive.paneViews()[0]!.renderer()!.draw(target as never)
  assert.deepEqual(arcs.slice(2), [
    [20, 330, 2.5, 'rgba(52, 199, 89, 0.9)'],
    [20, 270, 2.5, 'rgba(255, 59, 48, 0.9)'],
  ])

  primitive.detached()
  primitive.paneViews()[0]!.renderer()!.draw(target as never)
  assert.equal(arcs.length, 4)
})
