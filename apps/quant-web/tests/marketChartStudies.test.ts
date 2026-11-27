import assert from 'node:assert/strict'
import test from 'node:test'
import type { BarData } from '../src/types/market.ts'
import { MARKET_CHART_STUDY_BAR_LIMIT, marketChartStudyIssue, marketChartStudyRequest, marketChartStudyTailRequest, marketStudyLayerStatus, projectMarketChartStudyDisplay, projectMarketChartStudyTail, retryMarketStudyWhenBusy } from '../src/utils/marketChartStudies.ts'

const identity = { symbol: 'rb', frequency: '15m', seriesKind: 'actual_dominant' } as const
const bars: BarData[] = [1, 2, 3].map(index => ({
  time: `2026-11-20T07:${index * 15}:00Z`,
  open: 100, high: 100, low: 100, close: 100, volume: 12,
  physicalContract: 'RB2701', calculationSegmentId: 'RB2701:loaded-start',
  sourceBarSha256: 'c'.repeat(64),
  ...(index === 3 ? { confirmed: false } : {}),
}))

function wireBar(bar: BarData, source: NonNullable<BarData['marketSource']> = 'canonical') {
  return {
    source, bar_end: bar.time, trading_day: bar.trading_day,
    open: String(bar.open), high: String(bar.high), low: String(bar.low),
    close: String(bar.close), volume: String(bar.volume), source_bar_sha256: bar.sourceBarSha256,
  }
}

function fixtures() {
  const request = marketChartStudyRequest(identity, ['ema_21'], bars)!
  return {
    request,
    wire: {
      schema_version: 'guiyi_market_chart_studies_v1', result_schema_version: 'guiyi_feature_result_v1',
      symbol: 'rb', series_kind: 'actual_dominant', frequency: '15m', contract: null,
      as_of: request.query.last, source_revision: 'a'.repeat(64), unavailable_reason: null,
      segments: [{
        physical_contract: 'RB2701', segment_id: 'RB2701:window-start', calculation_anchor: request.bars[0]!.time,
        bars: request.bars.map(bar => wireBar(bar)),
        features: [{
          study: 'ema21', formula_version: 'talib_ema21_v1', backend_version: 'ta-lib:fixture',
          parameters_hash: 'b'.repeat(16),
          points: [
            { status: 'WARMING', values: null as Record<string, number> | null, diagnostic: 'LOOKBACK_REQUIRED' as string | null },
            { status: 'READY', values: { value: 0 }, diagnostic: null },
          ],
        }],
      }],
    },
  }
}

test('only requested EMA windows are sent, excluding live and preview bars', () => {
  const { request } = fixtures()
  assert.equal(request.query.count, 2)
  assert.equal(request.query.last, bars[1]!.time)
  assert.equal(request.query.studies, 'ema21')
  assert.equal(marketChartStudyRequest(identity, ['boll', 'ema_21'], bars)!.query.studies, 'boll,ema21')
  assert.equal(marketChartStudyRequest(identity, ['htdy'], bars), null)
  assert.equal(marketChartStudyRequest(identity, ['ema_21'], [{ ...bars[0]!, physicalContract: undefined }]), null)
  assert.equal(marketChartStudyRequest(identity, ['ema_21'], bars.slice(0, 2))!.key, request.key)
  assert.notEqual(marketChartStudyRequest(identity, ['ema_21'], [{ ...bars[0]!, close: 101 }, ...bars.slice(1)])!.key, request.key)
})

test('EMA request explicitly identifies omitted chart history and proves its bounded cutoff', () => {
  const history = Array.from({ length: MARKET_CHART_STUDY_BAR_LIMIT + 1 }, (_, index) => ({
    ...bars[0]!, time: new Date(Date.UTC(2026, 9, 1, 0, index * 15)).toISOString(),
  }))
  const request = marketChartStudyRequest(identity, ['ema_21'], history)!
  const withinBudget = marketChartStudyRequest(identity, ['ema_21'], history.slice(1))!
  assert.equal(request.truncatedBefore, true)
  assert.equal(withinBudget.truncatedBefore, false)
  assert.equal(request.key, withinBudget.key)
  assert.equal(request.query.first, history[1]!.time)
  assert.equal(request.query.last, history.at(-1)!.time)
})

test('EMA projection retains server point states and rejects mismatched evidence', () => {
  const { request, wire } = fixtures()
  const result = projectMarketChartStudyDisplay(wire, request)
  assert.equal(result?.points.ema_21?.[bars[0]!.time]?.status, 'WARMING')
  assert.equal(result?.points.ema_21?.[bars[1]!.time]?.values?.value, 0)
  assert.equal(result?.features.ema_21?.formulaVersion, 'talib_ema21_v1')
  for (const mutate of [
    (value: typeof wire) => { value.segments[0]!.physical_contract = 'RB2609' },
    (value: typeof wire) => { value.segments[0]!.bars[0]!.bar_end = '2026-11-20T07:15:00.000001Z' },
    (value: typeof wire) => { value.segments[0]!.bars[0]!.close = '101' },
    (value: typeof wire) => { value.segments[0]!.bars[0]!.source_bar_sha256 = 'd'.repeat(64) },
    (value: typeof wire) => { value.segments[0]!.features[0]!.formula_version = 'unregistered' },
    (value: typeof wire) => { value.segments[0]!.features[0]!.points[0]!.values = { value: 0 } },
    (value: typeof wire) => { value.segments[0]!.features[0]!.points[1]!.values = { value: Infinity } },
    (value: typeof wire) => { value.segments[0]!.features[0]!.points.pop() },
  ]) {
    const changed = structuredClone(wire); mutate(changed)
    assert.throws(() => projectMarketChartStudyDisplay(changed, request), /MARKET_CHART_STUDY_/)
  }
})

test('BOLL requires an aligned finite upper, middle and lower value from the shared read', () => {
  const request = marketChartStudyRequest(identity, ['boll'], bars)!
  const { wire } = fixtures()
  const feature = wire.segments[0]!.features[0]!
  feature.study = 'boll'
  feature.formula_version = 'talib_boll_v1'
  feature.points[1]!.values = { upper: 105, middle: 100, lower: 95 }
  assert.deepEqual(projectMarketChartStudyDisplay(wire, request)?.points.boll?.[bars[1]!.time]?.values,
    { upper: 105, middle: 100, lower: 95 })
  feature.points[1]!.values = { upper: 105, middle: 100 }
  assert.throws(() => projectMarketChartStudyDisplay(wire, request), error => {
    assert.deepEqual(marketChartStudyIssue(error), { status: 'catalog_mismatch', reason: 'MARKET_CHART_STUDY_OUTPUT_MISMATCH' })
    return true
  })
})

test('an incompatible result schema differs from rejected market input and compute output', () => {
  const { request, wire } = fixtures()
  const cases = [
    [{ ...wire, result_schema_version: 'future' }, 'catalog_mismatch', 'MARKET_CHART_STUDY_SCHEMA_MISMATCH'],
    [{ ...wire, symbol: 'other' }, 'invalid_source', 'MARKET_CHART_STUDY_IDENTITY_MISMATCH'],
  ] as const
  for (const [payload, status, reason] of cases) {
    assert.throws(() => projectMarketChartStudyDisplay(payload, request), error => {
      assert.deepEqual(marketChartStudyIssue(error), { status, reason })
      return true
    })
  }
  wire.segments[0]!.features[0]!.points[1]!.values = { value: Infinity }
  assert.throws(() => projectMarketChartStudyDisplay(wire, request), error => {
    assert.deepEqual(marketChartStudyIssue(error), { status: 'compute_error', reason: 'MARKET_CHART_STUDY_POINT_INVALID' })
    return true
  })
  for (const code of ['MARKET_CHART_STUDY_PHYSICAL_OWNER_INVALID', 'MARKET_CHART_STUDY_WINDOW_MISMATCH']) {
    assert.deepEqual(marketChartStudyIssue({ response: { status: 409, data: { detail: { code } } } }), {
      status: 'invalid_source', reason: code,
    })
  }
  assert.deepEqual(marketChartStudyIssue({ response: { status: 409, data: { detail: { code: 'unexpected-private-detail' } } } }), {
    status: 'missing_input', reason: 'MARKET_CHART_STUDY_REQUEST_FAILED',
  })
})
test('EMA explicitly reports continuous series without physical ownership as unavailable', () => {
  const { wire } = fixtures()
  const request = marketChartStudyRequest({ ...identity, seriesKind: 'continuous' }, ['ema_21'], bars)!
  const missing = { ...wire, series_kind: 'continuous', source_revision: null, unavailable_reason: 'PHYSICAL_OWNER_REQUIRED', segments: [] }
  assert.equal(projectMarketChartStudyDisplay(missing, request), null)
})

test('only the latest EMA request retries while the cancelled predecessor still occupies the server', async () => {
  const old = new AbortController()
  const current = new AbortController()
  let finishOld!: (value: string) => void
  const oldReply = new Promise<string>(resolve => { finishOld = resolve })
  const superseded = retryMarketStudyWhenBusy(() => oldReply, old.signal)
  const rejection = assert.rejects(superseded, { name: 'AbortError' })
  old.abort()
  let calls = 0
  const result = await retryMarketStudyWhenBusy(async () => {
    if (++calls === 1) {
      finishOld('old result')
      throw { response: { status: 503, data: { detail: { code: 'MARKET_CHART_STUDY_BUSY' } } } }
    }
    return 'latest result'
  }, current.signal)
  await rejection
  assert.equal(result, 'latest result')
  assert.equal(calls, 2)
})

test('cancelled EMA retry and genuine unavailable responses do not send another request', async () => {
  for (const code of ['MARKET_CHART_STUDY_BUSY', 'MARKET_CHART_STUDY_UNAVAILABLE']) {
    const controller = new AbortController()
    let calls = 0
    const pending = retryMarketStudyWhenBusy(async () => {
      calls++
      if (code === 'MARKET_CHART_STUDY_BUSY') setTimeout(() => controller.abort(), 5)
      throw { response: { status: 503, data: { detail: { code } } } }
    }, controller.signal)
    await assert.rejects(pending)
    assert.equal(calls, 1)
  }
})

test('chart study diagnostics distinguish missing, waiting, source rejection and compute errors', () => {
  assert.equal(marketStudyLayerStatus(), 'missing_input')
  assert.equal(marketStudyLayerStatus({ values: null, status: 'WARMING', diagnostic: 'LOOKBACK_REQUIRED' }), 'warming')
  assert.equal(marketStudyLayerStatus({ values: null, status: 'INVALID', diagnostic: 'INPUT_QUALITY_INVALID' }), 'invalid_source')
  assert.equal(marketStudyLayerStatus({ values: null, status: 'INVALID', diagnostic: 'OUTPUT_NONFINITE' }), 'compute_error')
  assert.equal(marketStudyLayerStatus({ values: null, status: 'ERROR', diagnostic: 'COMPUTE_FAILED' }), 'compute_error')
  const { request, wire } = fixtures()
  wire.segments[0]!.features[0]!.points[0]!.diagnostic = 'Unexpected private payload'
  assert.equal(projectMarketChartStudyDisplay(wire, request)?.points.ema_21?.[bars[0]!.time]?.diagnostic,
    'MARKET_CHART_STUDY_POINT_UNAVAILABLE')
})

test('tail demand uses completed Live and exact active Market samples, excluding retained prices', () => {
  const { request, wire } = fixtures()
  const history = projectMarketChartStudyDisplay(wire, request)!
  const completed = { ...bars[2]!, marketSource: 'completed_live' as const, trading_day: '2026-11-20' }
  const retained = { ...completed, marketSource: 'retained' as const }
  const activity = {
    bar: { ...completed, time: '2026-11-20T08:00:00Z', marketSource: 'active_preview' as const },
    generation: 'gen2', observedAt: '2026-11-20T07:46:01Z', receivedAt: '2026-11-20T07:46:02Z',
  }
  assert.equal(marketChartStudyTailRequest(request, history, [...request.bars, retained], true, null), null)
  const tail = marketChartStudyTailRequest(request, history, [...request.bars, completed], true, activity)!
  assert.equal(tail.query.completed_through, completed.time)
  assert.equal(tail.query.include_preview, true)
  assert.equal(tail.query.source_revision, history.sourceRevision)

  const daily = marketChartStudyRequest({ ...identity, frequency: '1d' }, ['ema_21'], request.bars)!
  assert.equal(marketChartStudyTailRequest(daily, history, [...daily.bars, retained], false, activity)?.query.include_preview, true)
})

test('historical proof accepts reseeded segments under the same physical owner', () => {
  const { request, wire } = fixtures()
  const segment = wire.segments[0]!
  wire.segments = [0, 1].map(index => ({
    ...segment, segment_id: `segment-${index}`,
    bars: [segment.bars[index]!],
    features: segment.features.map(feature => ({ ...feature, points: [feature.points[index]!] })),
  }))
  const projected = projectMarketChartStudyDisplay(wire, request)
  assert.equal(projected?.segmentsByTime[bars[1]!.time]?.segmentId, 'segment-1')
  wire.segments[1]!.calculation_anchor = bars[2]!.time
  assert.throws(() => projectMarketChartStudyDisplay(wire, request), /MARKET_CHART_STUDY_SEGMENT_INVALID/)
})

test('tail proof distinguishes completed Live from exact preview observation', () => {
  const { request, wire } = fixtures()
  const history = projectMarketChartStudyDisplay(wire, request)!
  const completed = { ...bars[2]!, marketSource: 'completed_live' as const, trading_day: '2026-11-20' }
  const activity = {
    bar: { ...completed, time: '2026-11-20T08:00:00Z', marketSource: 'active_preview' as const },
    generation: 'gen2', observedAt: '2026-11-20T07:46:01Z', receivedAt: '2026-11-20T07:46:02Z',
  }
  const demand = marketChartStudyTailRequest(request, history, [...request.bars, completed], true, activity)!
  const fixtureSegment = wire.segments[0]!
  function segment(bar: BarData) {
    return {
      ...fixtureSegment, bars: [wireBar(bar, bar.marketSource)],
      features: [{ ...fixtureSegment.features[0]!, points: [fixtureSegment.features[0]!.points[1]!] }],
    }
  }
  const payload = { ...wire, segments: [segment(completed)], tail_unavailable_reason: null,
    preview: { segment: segment(activity.bar), generation: activity.generation, observed_at: activity.observedAt, received_at: activity.receivedAt } }
  const result = projectMarketChartStudyTail(payload, demand)
  assert.equal(result.completed?.points.ema_21?.[completed.time]?.values?.value, 0)
  assert.equal(result.preview?.data.points.ema_21?.[activity.bar.time]?.values?.value, 0)
  for (const mutate of [
    (value: typeof payload) => { value.preview.generation = 'gen1' },
    (value: typeof payload) => { value.preview.observed_at = '2026-11-20T07:46:01.000001Z' },
    (value: typeof payload) => { value.preview.received_at = '2026-11-20T07:46:02.000001Z' },
    (value: typeof payload) => { value.preview.segment.bars[0]!.trading_day = '2026-11-21' },
    (value: typeof payload) => { value.preview.segment.bars[0]!.open = '1' },
  ]) {
    const changed = structuredClone(payload); mutate(changed)
    const result = projectMarketChartStudyTail(changed, demand)
    assert.equal(result.preview, null)
    assert.equal(result.completed?.points.ema_21?.[completed.time]?.status, 'READY')
  }
  const wrongSource = structuredClone(payload)
  wrongSource.segments[0]!.bars[0]!.source = 'retained'
  assert.throws(() => projectMarketChartStudyTail(wrongSource, demand), /MARKET_CHART_STUDY_BAR_MISMATCH/)
  assert.throws(() => projectMarketChartStudyTail({ ...payload, source_revision: 'f'.repeat(64) }, demand), /MARKET_CHART_STUDY_SOURCE_INVALID/)
})

test('TA-Lib MACD requires its own formula and three aligned outputs', () => {
  const { wire } = fixtures()
  const request = marketChartStudyRequest(identity, ['macd'], bars)!
  const feature = wire.segments[0]!.features[0]!
  feature.study = 'macd'
  feature.formula_version = 'talib_macd_12_26_9_v1'
  feature.points[1]!.values = { dif: 1, dea: 0.5, histogram: 0.5 }
  assert.equal(projectMarketChartStudyDisplay(wire, request)?.points.macd?.[bars[1]!.time]?.values?.histogram, 0.5)
  feature.formula_version = 'ths_macd_display_v1'
  assert.throws(() => projectMarketChartStudyDisplay(wire, request), /MARKET_CHART_STUDY_FEATURE_INVALID/)
})
