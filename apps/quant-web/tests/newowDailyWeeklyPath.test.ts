import assert from 'node:assert/strict'
import test from 'node:test'
import { dailyWeeklyPathGeometry } from '../src/utils/newowDailyWeeklyPath.ts'

const price = (raw: string) => ({ raw }) as any
const period = (frequency: '1d' | '1w', cost: string | null, target: string | null, state = 'hold') => ({ frequency, state, status:'ready' as const, cost:cost ? price(cost) : null, current:price('110'), target:target ? price(target) : null, reason:null })

test('daily and weekly path use one price scale, distinct cost, solid past and dashed future', () => {
  const view = dailyWeeklyPathGeometry([period('1w','90','160'),period('1d','101','125')])
  assert.equal(view[0].label,'周线')
  assert.ok(view[0].cost!.y > view[1].cost!.y)
  assert.equal(view[0].current!.y,view[1].current!.y)
  assert.ok(view[0].target!.y < view[1].target!.y)
  assert.equal(view[0].active,true)
})
test('flat and missing values never fabricate cost, target or price movement', () => {
  const view = dailyWeeklyPathGeometry([period('1d',null,null,'wait')])
  assert.equal(view[0].cost,null)
  assert.equal(view[0].target,null)
  assert.equal(view[0].active,false)
  assert.equal(view[0].current!.y,130)
})
test('nonfinite or nonpositive display values are unavailable', () => {
  const view = dailyWeeklyPathGeometry([period('1d','NaN','0')])
  assert.equal(view[0].cost,null)
  assert.equal(view[0].target,null)
})

import { buildNewowFixtureEnvelopeForTest, NEWOW_AS_OF } from '../e2e/newow-product.helpers.mjs'
import { normalizeNewowProductResponse } from '../src/utils/newowProductTypes.ts'

function pathWire() {
  const raw = buildNewowFixtureEnvelopeForTest('explanation','trend','1d') as any
  const source = (frequency: string, amount: string, category: string) => ({ raw:amount, frequency,bar_end:NEWOW_AS_OF, physical_contract:'RB2701',segment_id:'owner',calculation_segment_id:frequency+'-calc',source_identity:'canonical-revision',source_category:category })
  const rows = ['1w','1d'].map(frequency => ({ frequency,state:'hold',status:'ready',reason:null,
    formula_versions:['newow_escape_d123_page_v2','newow_trend_band_page_v2'],
    cost:{...source(frequency,frequency==='1w'?'90':'101','canonical_strategy_build'),entry_marker_id:frequency+'-entry'},
    current:source('1d','110','canonical_completed_close'),target:source(frequency,frequency==='1w'?'160':'125','canonical_channel'),
  }))
  raw.explanation.value.decision_v2 = {
    cdv2:{formula_version:'newow_composite_decision_cdv2_1_2_0_v1',as_of:NEWOW_AS_OF,executable:false,explanation_only:true,is_probability:false,is_margin_ratio:false,
      resonance:'R0',mismatch:null,action:'等待',action_code:'WAIT',scores:{trend:0,oscillation:0,resonance:0,direction:0,volatility:0},deductions:{j_reduce:0,care:0,tent:0},total:0,cert_extra:0,certainty_cap:0,resonance_cap:0,reference_exposure_cap:0,
      trend_state:{week:'up',day:'up',m60:'unknown'},oscillation_state:{week:'idle',day:'idle',m60:'idle'},missing_roles:['trend_m60','oscillation_m60'],
      facts:['trend_week','trend_day','trend_m60','oscillation_week','oscillation_day','oscillation_m60'].map(role=>({role,age:-1,bar_end:role.endsWith('m60')?null:NEWOW_AS_OF,state:role.startsWith('trend')&&!role.endsWith('m60')?'hold':null,physical_contract:'RB2701',segment_id:'owner'})),
    },prices:null,daily_weekly_path:{version:'guiyi_daily_weekly_path_v1',as_of:NEWOW_AS_OF,page_parity:true,executable:false,source_note:'同周期 canonical path',periods:rows},
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
    (path: any)=>path.executable=true,
  ]) {
    const raw = pathWire(); mutate(raw.explanation.value.decision_v2.daily_weekly_path)
    assert.throws(()=>normalizeNewowProductResponse(raw,pathRequest),/path/)
  }
})
