import assert from 'node:assert/strict'
import test from 'node:test'
import {normalizeExperiment,ExperimentRequestGeneration} from '../src/utils/newowExperiments.ts'
const request={product:'rb',frequency:'1d',kind:'osc-test',as_of:'2026-10-08T07:00:00Z'} as const
const fixture=()=>({...request,schema_version:'newow_experiment_detail_v1',formula_version:'newow_osc_test_page_v3379_v1',page_parity:true,executable:false,readiness:{status:'READY',reason_code:null},segments:[{segment_id:'a',physical_contract:'RB2701',status:'CURRENT',ordinary:null,theoretical:null}],bars:[{bar_end:'2026-10-07T07:00:00Z',trading_day:'2026-10-08',segment_id:'a',physical_contract:'RB2701',open:'100',high:'110',low:'90',close:'101',channel_high:'110',channel_low:'90'}],markers:[{marker_id:'b',bar_end:'2026-10-07T07:00:00Z',segment_id:'a',physical_contract:'RB2701',action:'BUILD',reference_price:'90',score:0,break_label:null,stop_loss:false,confirm_exit:false}]})
test('accepts independent experimental identity and decimal lexemes',()=>assert.equal(normalizeExperiment(fixture(),request).markers[0]!.reference_price,'90'))
test('rejects future, mismatched strategy, physical owner and duplicate marker',()=>{for(const mutate of [(v:any)=>v.kind='osc-test2',(v:any)=>v.executable=true,(v:any)=>v.bars[0].bar_end='2099-01-01T00:00:00Z',(v:any)=>v.markers[0].physical_contract='RB2610',(v:any)=>v.markers.push({...v.markers[0]}),(v:any)=>v.bars[0].close='NaN']){const v=fixture();mutate(v);assert.throws(()=>normalizeExperiment(v,request))}})
test('new selection and clear abort and reject stale responses',()=>{const g=new ExperimentRequestGeneration();const a=g.begin();const b=g.begin();assert.equal(a.signal.aborted,true);assert.equal(a.current(),false);assert.equal(b.current(),true);g.clear();assert.equal(b.signal.aborted,true);assert.equal(b.current(),false)})

import {experimentRangeParams} from '../src/utils/newowExperiments.ts'
test('range uses snapshot Shanghai day and bounded chart independently from statistics',()=>{assert.deepEqual(experimentRangeParams('2026-10-08T18:00:00Z','year'),{from:'2026-01-01',through:'2026-10-09',chart_limit:2000});assert.deepEqual(experimentRangeParams('2026-10-08T07:00:00Z','all'),{all_history:true,chart_limit:2000})})

test('rejects version spoof, noncompleted instant, malformed OHLC and action score',()=>{for(const mutate of [(v:any)=>v.formula_version='old_version',(v:any)=>v.bars[0].bar_end=request.as_of,(v:any)=>v.bars[0].low='102',(v:any)=>v.bars[0].high='90',(v:any)=>v.markers[0].score=101,(v:any)=>v.markers[0].stop_loss=true]){const v=fixture();mutate(v);assert.throws(()=>normalizeExperiment(v,request))}})
test('rejects forged ordinary/theory model identity and invalid trade times',()=>{
 const model=()=>({model_version:'newow_oscillation_experiment_ordinary_v3379_v1',page_parity:true,executable:false,hindsight:false,summary:{cum_return_percentage_points:'0',accuracy_pct:'0',max_drawdown_percentage_points:'0',trade_count:0},dates:[],equity:[],trades:[]})
 for(const mutate of [(m:any)=>m.model_version='old',(m:any)=>m.hindsight=true,(m:any)=>m.dates=['bad'],(m:any)=>m.dates=[request.as_of],(m:any)=>m.trades=[{segment_id:'a',physical_contract:'RB2701',entry_reference_price:'90',exit_reference_price:'91',return_percentage_points:'1',entry_bar_end:'bad',exit_bar_end:'2026-10-07T07:00:00Z',stop_loss:false,confirm_exit:false,force_close:false}]] ){const v=fixture() as any;v.segments[0].ordinary=model();mutate(v.segments[0].ordinary);assert.throws(()=>normalizeExperiment(v,request))}
})

// Minimal witness from the real candidate wire: final bar 07:00:00,
// accepted snapshot 07:00:00.000001. No full market sample is retained.
test('real candidate microsecond cutoff accepts completed bar, curve and terminal trade', () => {
 const as_of='2026-10-08T07:00:00.000001+00:00'
 const end='2026-10-08T07:00:00+00:00'
 const v=fixture() as any
 v.as_of=as_of
 v.bars[0].bar_end=end
 v.markers[0].bar_end=end
 v.segments[0].ordinary={model_version:'newow_oscillation_experiment_ordinary_v3379_v1',page_parity:true,executable:false,hindsight:false,summary:{cum_return_percentage_points:'0',accuracy_pct:'0',max_drawdown_percentage_points:'0',trade_count:1},dates:[end],equity:['0'],trades:[{segment_id:'a',physical_contract:'RB2701',entry_reference_price:'90',exit_reference_price:'90',return_percentage_points:'0',entry_bar_end:end,exit_bar_end:end,stop_loss:false,confirm_exit:false,force_close:true}]}
 const query={...request,as_of:'2026-10-08T07:00:00.000001Z'}
 assert.equal(normalizeExperiment(v,query).bars.length,1)
 for(const target of ['bar','curve','trade']){
  const forged=structuredClone(v)
  if(target==='bar')forged.bars[0].bar_end=as_of
  if(target==='curve')forged.segments[0].ordinary.dates[0]=as_of
  if(target==='trade')forged.segments[0].ordinary.trades[0].exit_bar_end=as_of
  assert.throws(()=>normalizeExperiment(forged,query))
 }
 assert.throws(()=>normalizeExperiment(v,{...query,as_of:'2026-10-08T07:00:00.000002Z'}))
})
