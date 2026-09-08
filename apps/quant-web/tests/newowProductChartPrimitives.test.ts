import assert from 'node:assert/strict'
import * as primitives from '../src/components/market/detail/newow/newowProductChartPrimitives.ts'
import test from 'node:test'

import {
  buildNewowAuxiliaryChartModel,
  buildNewowAuxiliaryDisclosure,
  buildNewowProductChartModel,
  chartMarkerTime,
  resolveNewowAuxiliaryRenderState,
} from '../src/components/market/detail/newow/newowProductChartPrimitives.ts'
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
  value.bars[1] = { ...value.bars[1]!, physical_contract: 'JM2605', segment_id: 'segment-2' }

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
      schema_version: 'newow_product_detail_v1',
      identity: { product: 'jm', strategy, frequency, series_kind: 'actual_dominant', profile_id: `newow_product_${strategy}_${frequency}_v1`, formula_versions: formulas },
      as_of: '2026-08-15T09:00:00Z', read_at: '2026-08-15T09:00:01Z', input_content_sha256: 'a'.repeat(64),
      data_revision_identity: null, snapshot_token: 'snapshot-a', reference_model_version: 'newow_marker_reference_zero_cost_v1',
      futures_adaptation_version: 'newow_futures_segment_interrupt_v1',
    },
    section: 'chart',
    status: { status: 'ready', evidence_status: 'ACTIVE_CODE_VERIFIED', reason_code: null },
    value: {
      chart_from: '2026-08-14', chart_through: '2026-08-15', page_identity: 'b'.repeat(64), bars,
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
    volume: 10, open_interest: 20, physical_contract: 'JM2601', segment_id: 'segment-1',
    source_identity: 'canonical:jm:JM2601', observation_eligible: true, completed: true as const,
  }
}

type MutableChartResponse = {
  -readonly [K in keyof NewowProductSectionResponse<'chart'>]: NewowProductSectionResponse<'chart'>[K] extends object
    ? Mutable<NewowProductSectionResponse<'chart'>[K]>
    : NewowProductSectionResponse<'chart'>[K]
}
type Mutable<T> = { -readonly [K in keyof T]: T[K] extends readonly (infer U)[] ? Mutable<U>[] : T[K] extends object ? Mutable<T[K]> : T[K] }


test('missing and warming main values break runs and trend band, including an absent frame', () => {
  const response = chartResponse('trend', '60m')
  const value = response.value!
  const third = bar('2026-08-16T07:00:00Z', '2026-08-16', '102')
  value.bars.push(third)
  value.frames.push({ ...structuredClone(value.frames[1]!), bar_end: third.bar_end })
  value.frames[1]!.main_values.a = null
  let model = buildNewowProductChartModel(response)
  assert.deepEqual(model.mainLines.filter(line => line.key === 'a').map(line => line.points.length), [1, 1])
  assert.equal(model.bandAreas.length, 0)
  value.frames.splice(1, 1)
  model = buildNewowProductChartModel(response)
  assert.deepEqual(model.mainLines.filter(line => line.key === 'b').map(line => line.points.length), [1, 1])
  value.frames[1]!.status.status = 'warming'
  assert.equal(buildNewowProductChartModel(response).mainLines.filter(line => line.key === 'b').length, 1)
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


test('band primitive paints authoritative coordinates and releases attachment on detach', async () => {
  const { NewowProductBandPrimitive } = await import('../src/components/market/detail/newow/newowProductBandPrimitive.ts')
  const model = buildNewowProductChartModel(chartResponse('trend', '1d'))
  assert.equal(model.bandAreas.length, 1)
  const primitive = new NewowProductBandPrimitive()
  const coordinates: unknown[] = []
  const polygons: number[][] = []
  let updates = 0
  const target = { useMediaCoordinateSpace(callback: (scope: { context: object }) => void) { callback({ context: { save() {}, restore() {}, beginPath() {}, closePath() {}, fill() {}, moveTo(x: number, y: number) { polygons.push([x, y]) }, lineTo(x: number, y: number) { polygons.push([x, y]) } } }) } }
  primitive.attached({ chart: { timeScale: () => ({ timeToCoordinate(time: unknown) { coordinates.push(time); return coordinates.length * 10 } }) }, series: { priceToCoordinate: (price: number) => price }, requestUpdate: () => { updates++ } } as never)
  primitive.setData(model.bandAreas)
  primitive.paneViews()[0]!.renderer()!.draw(target as never)
  assert.equal(updates, 1)
  assert.deepEqual(coordinates, [{ year: 2026, month: 8, day: 14 }, { year: 2026, month: 8, day: 15 }])
  assert.deepEqual(polygons, [[10, 99], [20, 100], [20, 102], [10, 101]])
  primitive.detached(); primitive.setData(model.bandAreas)
  primitive.paneViews()[0]!.renderer()!.draw(target as never)
  assert.equal(updates, 1)
  assert.equal(polygons.length, 4)
})
