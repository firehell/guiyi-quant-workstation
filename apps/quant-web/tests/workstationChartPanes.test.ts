import assert from 'node:assert/strict'
import test from 'node:test'
import { archiveReadError, paneAvailability, matchedArchiveChart, readWorkstationLayers } from '../src/utils/workstationChartPanes.ts'
import type { MarketAfterCloseFrame, MarketAfterCloseSection } from '../src/types/referenceTrading.ts'
import type { BarData } from '../src/types/market.ts'
import { marketChartStudyRequest, marketChartStudyTailRequest, projectMarketChartStudyDisplay } from '../src/utils/marketChartStudies.ts'

const time = '2025-05-20T07:00:00Z', hash = 'a'.repeat(64)
const bar: BarData = { time, trading_day: '2025-05-20', sourceBarSha256: hash, open: 100, high: 102, low: 98, close: 101,
  marketSource: 'canonical', physicalContract: 'RB2510', calculationSegmentId: 'RB2510:2025-03-01', volume: 20 }
const frame = { bar_end: time, source_bar_sha256: hash, physical_contract: 'RB2510', calculation_segment_id: 'historical-owner-A',
  trading_day: bar.trading_day } as MarketAfterCloseFrame
const row = { ...frame, open: '100', high: '102', low: '98', close: '101', volume: 20, completed: true, observation_eligible: true }
const section = { status: 'ready', chart: { value: { bars: [row] } } } as unknown as MarketAfterCloseSection

test('archive panes require the historical owner, calculation segment, SHA, OHLCV and completed canonical bar', () => {
  assert.deepEqual(matchedArchiveChart(section, [frame], [bar])?.value.bars, [row])
  for (const change of [{ physicalContract: 'RB2701' }, { sourceBarSha256: 'b'.repeat(64) }, { volume: 21 },
    { marketSource: 'completed_live' as const }, { confirmed: false }]) {
    assert.equal(matchedArchiveChart(section, [frame], [{...bar, ...change}]), null)
  }
  assert.equal(matchedArchiveChart(section, [{...frame, calculation_segment_id: 'new-owner'}], [bar]), null)
})

test('archive errors distinguish a failed service, a changed receipt and an unreadable request', () => {
  assert.match(archiveReadError({ response: { status: 503, data: { detail: { code: 'SERVICE_BINDING_ROOT_UNAVAILABLE' } } } }), /503.*SERVICE_BINDING_ROOT_UNAVAILABLE/)
  assert.match(archiveReadError(new Error('REFERENCE_SNAPSHOT_CHANGED')), /快照版本冲突/)
  assert.match(archiveReadError({ response: { status: 422 } }), /读取失败（422）/)
})

test('per-pane status distinguishes a warming historical owner from the current weekly reason', () => {
  const latest = { bar_end: time, physical_contract: 'RB2510', calculation_segment_id: 'owner' }
  const chart = { value: { bars: [latest] } }
  const historical = { physical_contract: 'RB2505', segment_id: 'other', bar_ends: [], status: { status: 'warming' } }
  const current = { physical_contract: 'RB2510', segment_id: 'owner', bar_ends: [time], status: { status: 'ready', reason_code: null } }
  const aux = { status: { status: 'warming', reason_code: 'NEWOW_TREND_REVERSAL_WARMING' }, value: { component: 'trend_reversal', segments: [historical, current] } }
  assert.match(paneAvailability(chart, aux), /当前合约段就绪，历史有 1 个区段数据不完整/)
  current.status = { status: 'warming', reason_code: 'NEWOW_TREND_REVERSAL_WARMING' }
  assert.match(paneAvailability(chart, aux), /当前合约段预热中.*NEWOW_TREND_REVERSAL_WARMING/)
  assert.match(paneAvailability(chart, { status: { status: 'unavailable', reason_code: 'INPUT_CONFLICT' }, value: null }), /不可用.*INPUT_CONFLICT/)
})

test('default one pane, explicit zero, ordered distinct three and bounded heights', () => {
  assert.deepEqual(readWorkstationLayers(null).panes, [{id:'zhaoyao_mirror',height:144}])
  assert.deepEqual(readWorkstationLayers({panes:[]}).panes, [])
  assert.deepEqual(readWorkstationLayers({overlays:['boll','boll','arbitrary'],panes:[
    {id:'macd',height:96},{id:'macd',height:200},{id:'unknown'}, {id:'trend_reversal',height:999},{id:'up_down_energy',height:200},
    {id:'main_force_control',height:96},
  ]}), {overlays:['boll'],panes:[{id:'macd',height:96},{id:'trend_reversal',height:144},{id:'up_down_energy',height:200}]})
})

test('workstation uses a historical-only Quant Core request, verifies fixed settings and never seeds a live tail', () => {
  const identity = {symbol:'rb',seriesKind:'actual_dominant',frequency:'1d',profile:'newow'} as const
  const request = marketChartStudyRequest(identity, ['ema_10'], [bar])!
  assert.equal(request.query.profile, 'newow')
  assert.equal(marketChartStudyRequest(identity, ['ema_10'], [{...bar, sourceBarSha256:undefined}]), null)
  assert.equal(marketChartStudyRequest(identity, ['ema_10'], [{...bar, confirmed:false}]), null)
  const feature = {study:'ema10',formula_version:'talib_ema10_v1',parameters_hash:'98f49abca86eb526',
    backend_version:'ta-lib:fixture',points:[{status:'READY',values:{value:100.5},diagnostic:null}]}
  const body = {schema_version:'guiyi_market_chart_studies_v1',result_schema_version:'guiyi_feature_result_v1',
    symbol:'rb',series_kind:'actual_dominant',frequency:'1d',contract:null,as_of:time,source_revision:hash,unavailable_reason:null,
    segments:[{physical_contract:'RB2510',segment_id:'historical-block',calculation_anchor:time,
      bars:[{...row,volume:String(row.volume),source:'canonical'}],features:[feature]}]}
  const data = projectMarketChartStudyDisplay(body,request)!
  assert.equal(data.points.ema_10?.[time]?.values?.value,100.5)
  assert.equal(marketChartStudyTailRequest(request,data,[{...bar,marketSource:'completed_live'}],true,null),null)
  feature.parameters_hash = 'b'.repeat(16)
  assert.throws(() => projectMarketChartStudyDisplay(body,request), /FEATURE_IDENTITY_MISMATCH/)
})
