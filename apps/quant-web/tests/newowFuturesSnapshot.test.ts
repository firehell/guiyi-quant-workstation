import assert from 'node:assert/strict'
import test from 'node:test'
import { createFuturesSnapshotResource, validateFuturesSnapshot, futuresChartBars, futuresChartMarkers, futuresChartCallouts } from '../src/utils/newowFuturesSnapshot.ts'
import type { FuturesSnapshot } from '../src/types/newowFutures.ts'
import type { MarketDetailIdentity } from '../src/types/marketDetail.ts'
const identity:MarketDetailIdentity={view:'newow',symbol:'jm',strategy:'trend',strategyModel:'futures_bidir_v1',frequency:'5m',seriesKind:'actual_dominant'}
function packet(symbol='jm'): FuturesSnapshot { return { schema_version:1, run_id:symbol,sha256:'a'.repeat(64),metadata:{run_id:symbol,strategy_model:'futures_bidir_v1',strategy:'trend',product:symbol.toUpperCase(),frequency:'5m',scenario:'baseline',as_of:'2026-10-19T15:00:00+08:00',status:'RESEARCH_ONLY',input_snapshot_hash:'b'.repeat(64),execution_facts_hash:'c'.repeat(64),profile_id:'newow_futures_trend_5m_100k_v1',auto_order:false,source:'historical_replay'},summary:{},reference:{summary:{},snapshot:null,actions:[{action_id:'entry',bar_end:'2026-10-19T14:55:00+08:00',side:'SHORT',physical_contract:'JM2701',owner_segment_id:'one',kind:'BUILD'}],trades:[],equity:[]},chart:{bars:[{bar_end:'2026-10-19T14:55:00+08:00',physical_contract:'JM2701',owner_segment_id:'one',open:'1.5',high:'2',low:'1',close:'1.75',volume:'20'}],frames:[]},diagnostics:{} } }
test('frozen packet validates full request identity, chart owner and historical cutoff',()=>{
  assert.equal(validateFuturesSnapshot(packet(),identity).run_id,'jm')
  for(const change of [{strategy:'main_rise'},{strategy_model:'old'},{product:'rb'},{frequency:'1d'},{scenario:'double_cost'}]) {const p=packet();Object.assign(p.metadata,change);assert.throws(()=>validateFuturesSnapshot(p,identity),/RESULT_IDENTITY_MISMATCH/)}
  for(const change of [{bar_end:'2026-10-20T00:00:00+08:00'},{owner_segment_id:null},{close:NaN},{close:1.75}]){const p=packet();Object.assign(p.chart.bars[0]!,change);assert.throws(()=>validateFuturesSnapshot(p,identity),/RESULT_CHART_INVALID/)}
  const blocked=packet();blocked.metadata.status='EXECUTION_FACTS_MISSING';blocked.metadata.execution_facts_hash=null;assert.equal(validateFuturesSnapshot(blocked,identity),blocked)
  const inapplicable=packet();inapplicable.metadata.status='NOT_APPLICABLE';inapplicable.metadata.input_snapshot_hash=null;inapplicable.metadata.execution_facts_hash=null;inapplicable.chart.bars=[];assert.equal(validateFuturesSnapshot(inapplicable,identity),inapplicable)
  const p=packet();p.chart.bars=Array(2001).fill(p.chart.bars[0]);assert.throws(()=>validateFuturesSnapshot(p,identity),/RESULT_IDENTITY/)
})
test('display converts decimals only for chart and drops mismatched markers',()=>{
  const p=packet();assert.equal(futuresChartBars(p)[0]?.close,1.75);assert.equal(futuresChartMarkers(p)[0]?.label,'建仓 空头')
  p.reference.actions[0]!.owner_segment_id='other';assert.equal(futuresChartMarkers(p).length,0)
})
test('abort ownership protects rapid switch and browser-back against late packets',async()=>{
  const pending:Array<{resolve:(p:FuturesSnapshot)=>void;signal:AbortSignal}>=[], updates:any[]=[]
  const resource=createFuturesSnapshotResource((_i,signal)=>new Promise(resolve=>pending.push({resolve,signal})),(...args)=>updates.push(args))
  const a=resource.load(identity),b=resource.load({...identity,symbol:'rb'}),back=resource.load(identity)
  assert.equal(pending[0]!.signal.aborted,true);assert.equal(pending[1]!.signal.aborted,true)
  pending[2]!.resolve(packet());await back
  pending[1]!.resolve(packet('rb'));await b;pending[0]!.resolve(packet());await a
  assert.equal(updates.filter(([p])=>p).length,1);assert.equal(updates.at(-1)[0].run_id,'jm')
  const stale=resource.load(identity);resource.dispose();pending[3]!.resolve(packet());await stale;assert.equal(updates.at(-1)[0],null)
})

test('uncovered products stay explicit without dispatching strategy requests',async()=>{
  let fetched=false;const states:any[]=[]
  const resource=createFuturesSnapshotResource(async()=>{fetched=true;return packet()},(...args)=>states.push(args))
  await resource.load({...identity,symbol:'cu'})
  assert.equal(fetched,false);assert.deepEqual(states.at(-1),[null,false,'RESEARCH_NOT_COVERED'])
})

test('actual reference actions render Chinese markers and preserve authoritative anchor prices',()=>{
  const p=packet()
  p.reference.actions=['OPEN_LONG','OPEN_SHORT','CLOSE','ADD','REDUCE'].map((action,index)=>({action_id:`actual-${index}`,action,side:action==='OPEN_SHORT'?'SHORT':'LONG',at:p.chart.bars[0]!.bar_end,physical_contract:'JM2701',price:'1.625',reference_price:'1.650'}))
  const markers=futuresChartMarkers(p),callouts=futuresChartCallouts(p)
  assert.deepEqual(markers.map(m=>m.label),['开多 多头','开空 空头','清仓 多头','加仓 多头','减仓 多头'])
  assert.equal(markers[0]?.position,'belowBar');assert.equal(markers[1]?.position,'aboveBar');assert.equal(markers[2]?.position,'aboveBar')
  assert.equal(callouts.length,5);assert.equal(callouts[0]?.price,'1.650');assert.equal(callouts[0]?.physicalContract,'JM2701')
  p.reference.actions[0]!.owner_segment_id='other';assert.equal(futuresChartCallouts(p).length,4)
  p.reference.actions[1]!.physical_contract='JM2609';assert.equal(futuresChartMarkers(p).length,3)
})

test('minute protection at 09:47 plots on proven enclosing 09:50 bar without changing its source price/time',()=>{
  const p=packet(),template=p.chart.bars[0]!
  p.chart.bars=['09:45','09:50'].map(time=>({...template,bar_end:`2026-10-19T${time}:00+08:00`}))
  p.reference.actions=[{action_id:'protective-0947',action:'CLOSE',side:'LONG',at:'2026-10-19T09:47:00+08:00',bar_end:'2026-10-19T09:47:00+08:00',display_bar_end:'2026-10-19T09:50:00+08:00',price:'1.625',reference_price:'1.650',physical_contract:'JM2701',owner_segment_id:'one'}]
  assert.equal(validateFuturesSnapshot(p,identity),p)
  const marker=futuresChartMarkers(p)[0]!,callout=futuresChartCallouts(p)[0]!
  assert.equal(marker.time,'2026-10-19T09:50:00+08:00');assert.match(marker.label,/09:47/);assert.match(marker.tooltip!,/09:47/)
  assert.equal(callout.time,marker.time);assert.equal(callout.price,'1.650');assert.match(callout.title,/09:47/)
  assert.equal(p.reference.actions[0]!.bar_end,'2026-10-19T09:47:00+08:00')
  for(const change of [{display_bar_end:'2026-10-19T09:55:00+08:00'},{at:'2026-10-19T09:44:00+08:00'},{at:'2026-10-19T09:51:00+08:00'},{physical_contract:'JM2609'},{owner_segment_id:'other'}]){
    const invalid=structuredClone(p);Object.assign(invalid.reference.actions[0]!,change)
    assert.throws(()=>validateFuturesSnapshot(invalid,identity),/RESULT_ACTION_COORDINATE_INVALID/)
  }
  delete p.reference.actions[0]!.display_bar_end
  assert.equal(validateFuturesSnapshot(p,identity),p);assert.equal(futuresChartMarkers(p).length,0,'unannotated partial-period actions remain records only')
})
