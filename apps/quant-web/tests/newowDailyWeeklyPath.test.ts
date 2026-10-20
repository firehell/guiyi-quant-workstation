import assert from 'node:assert/strict'
import test from 'node:test'

import { buildNewowFixtureEnvelopeForTest, NEWOW_AS_OF } from '../e2e/newow-product.helpers.mjs'
import { normalizeNewowProductResponse } from '../src/utils/newowProductTypes.ts'

function pathWire() {
  const raw = buildNewowFixtureEnvelopeForTest('explanation','trend','1d') as any
  const source = (frequency: string, amount: string, category: string) => ({ raw:amount, frequency,bar_end:NEWOW_AS_OF, physical_contract:'RB2701',segment_id:'owner',calculation_segment_id:frequency+'-calc',source_identity:'canonical-revision',source_category:category })
  const rows = ['1w','1d','60m'].map(frequency => ({ frequency,state:'hold',status:'ready',reason:null,
    formula_versions:['newow_escape_d123_page_v2','newow_trend_band_page_v3','newow_trend_marker_initial_clear_v2'],
    cost:{...source(frequency,frequency==='1w'?'90':'101','canonical_strategy_build'),entry_marker_id:frequency+'-entry'},
    current:source('1d','110','canonical_completed_close'),target:source(frequency,frequency==='1w'?'160':'125','canonical_channel'),
  }))
  raw.explanation.value.decision_v2 = {
    cdv2:{formula_version:'newow_composite_decision_cdv2_1_2_0_v1',as_of:NEWOW_AS_OF,executable:false,explanation_only:true,is_probability:false,is_margin_ratio:false,
      resonance:'R0',mismatch:null,action:'等待',action_code:'WAIT',scores:{trend:0,oscillation:0,resonance:0,direction:0,volatility:0},deductions:{j_reduce:0,care:0,tent:0},total:0,cert_extra:0,certainty_cap:0,resonance_cap:0,reference_exposure_cap:0,
      trend_state:{week:'up',day:'up',m60:'up'},oscillation_state:{week:'idle',day:'idle',m60:'idle'},missing_roles:['oscillation_m60'],
      facts:['trend_week','trend_day','trend_m60','oscillation_week','oscillation_day','oscillation_m60'].map(role=>({role,age:-1,bar_end:role.startsWith('trend')?NEWOW_AS_OF:null,state:role.startsWith('trend')?'hold':null,physical_contract:'RB2701',segment_id:'owner'})),
    },prices:null,daily_weekly_path:{version:'guiyi_daily_weekly_path_v2',as_of:NEWOW_AS_OF,page_parity:true,executable:false,source_note:'同周期 canonical path',periods:rows},
  }
  return raw
}
const pathRequest = {product:'rb',strategy:'trend',frequency:'1d',seriesKind:'actual_dominant',section:'explanation',asOf:NEWOW_AS_OF} as const

test('runtime normalizer preserves full independent daily weekly path sources', () => {
  const parsed = normalizeNewowProductResponse(pathWire(),pathRequest)
  assert.equal(parsed.section,'explanation')
  const path = (parsed.value as any).decision_v2.daily_weekly_path
  assert.equal(path.periods[0].cost.raw,'90')
  assert.equal(path.periods[1].cost.raw,'101')
  assert.equal(path.periods[0].cost.entry_marker_id,'1w-entry')
})
test('runtime normalizer rejects path identity, source category, future and pre-entry current', () => {
  for (const mutate of [
    (path: any)=>path.periods[0].cost.physical_contract='RB2610',
    (path: any)=>path.periods[0].target.segment_id='foreign',
    (path: any)=>path.periods[0].target.calculation_segment_id='foreign',
    (path: any)=>path.periods[0].cost.entry_marker_id='',
    (path: any)=>path.periods[0].target.frequency='1d',
    (path: any)=>path.periods[0].target.source_category='page_batch',
    (path: any)=>path.periods[0].current.bar_end='2099-09-27T07:00:00Z',
    (path: any)=>path.periods[0].current.bar_end='2000-09-27T07:00:00Z',
    (path: any)=>path.periods[2].target.frequency='1d',
    (path: any)=>path.periods[2].cost.segment_id='old',
    (path: any)=>path.periods[2].target.calculation_segment_id='old',
    (path: any)=>path.executable=true,
  ]) {
    const raw = pathWire(); mutate(raw.explanation.value.decision_v2.daily_weekly_path)
    assert.throws(()=>normalizeNewowProductResponse(raw,pathRequest),/path/)
  }
})

import { historicalPathGeometry } from '../src/utils/newowDailyWeeklyPath.ts'
function historyWire(){
  const raw=pathWire(),p=raw.explanation.value.decision_v2.daily_weekly_path
  p.version='guiyi_daily_weekly_path_v3'
  p.history={version:'newow_historical_path_v3402_v1',status:'ready',reason:null,holding:true,current:'110',target:'125',cost:'100',page_parity:true,executable:false,
    buys:[{date:'2026-08-01',price:'100'},{date:'2026-08-15',price:'105'}],sells:[{date:'2026-08-08',price:'120'}],background:[],eta:null,
    source:{physical_contract:'RB2701',segment_id:'owner',calculation_segment_id:'1d-calc',bar_end:NEWOW_AS_OF,as_of:NEWOW_AS_OF,strategy:'trend',price_source:'canonical_channel',background_status:'unavailable'}}
  return raw
}
test('new history rejects invalid prices, owner, sample, order and future points',()=>{
  normalizeNewowProductResponse(historyWire(),pathRequest)
  for(const mutate of [(h:any)=>h.current='bad',(h:any)=>h.source.physical_contract='OTHER',(h:any)=>h.buys=[],(h:any)=>h.buys.reverse(),(h:any)=>h.buys[1].date='2099-01-01']){
    const raw=historyWire();mutate(raw.explanation.value.decision_v2.daily_weekly_path.history)
    assert.throws(()=>normalizeNewowProductResponse(raw,pathRequest))
  }
})
test('history geometry has bounded labels, hollow points and separate buy/sell paths',()=>{
  const h=historyWire().explanation.value.decision_v2.daily_weekly_path.history
  for(const width of [480,1200]){
    const g=historicalPathGeometry(h,width)
    assert.equal(g.buy.length,2);assert.equal(g.sell.length,1)
    assert.ok(g.segments.some(s=>s.holding));assert.ok(g.segments.some(s=>!s.holding))
    assert.ok(g.labels.every(l=>Number.isFinite(l.y)&&l.x>=45&&l.x<=width-100))
    assert.ok(!g.envelope.includes('NaN'))
  }
})

test('Shanghai historical dates accept an overnight UTC cutoff without admitting tomorrow',()=>{
  const asOf='2026-09-03T17:00:00Z',raw=JSON.parse(JSON.stringify(historyWire()).replaceAll(NEWOW_AS_OF,asOf))
  raw.meta.as_of=asOf;raw.meta.read_at='2026-09-03T17:01:00Z'
  const d=raw.explanation.value.decision_v2
  d.cdv2.as_of=asOf;d.daily_weekly_path.as_of=asOf
  const h=d.daily_weekly_path.history;h.source.as_of=asOf
  h.buys[1].date='2026-09-04';h.background=[{start:'2026-09-03',end:'2026-09-04',state:'hold'}]
  normalizeNewowProductResponse(structuredClone(raw),{...pathRequest,asOf})
  h.buys[1].date='2026-09-05'
  assert.throws(()=>normalizeNewowProductResponse(raw,{...pathRequest,asOf}))
})
