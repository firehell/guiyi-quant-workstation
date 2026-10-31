import test from 'node:test'
import assert from 'node:assert/strict'
import {createHash} from 'node:crypto'
import {displayIndexVisible,layoutDisplayLabels,drawDisplayLabels,normalizeDisplayEvents,trendReversalBadge,type NewowDisplayEvent} from '../src/utils/newowDisplayEvents.ts'
const bar=(i:number)=>({bar_end:`2026-10-${String(10+i).padStart(2,'0')}T07:00:00Z`,physical_contract:'JM2701',segment_id:'owner',calculation_segment_id:'calc',close:'3797.24'})
const bars=Array.from({length:5},(_,i)=>bar(i))
function event(i=0,kind:NewowDisplayEvent['kind']='OSC_BREAKDOWN'):NewowDisplayEvent {
 return {...bar(i),event_id:createHash('sha256').update(kind+String(i)).digest('hex'),display_version:'newow_public_display_v3431_v1',kind,
 source_strategy:kind==='OSC_BREAKDOWN'?'oscillation':kind==='MAIN_RISE_J'?'main_rise':'trend_reversal',formula_version:'formula',frequency:'1d',known_at:bar(i).bar_end,
 source_build_id:kind==='OSC_BREAKDOWN'?'build':null,build_bar_end:kind==='OSC_BREAKDOWN'?bar(0).bar_end:null,build_threshold:kind==='OSC_BREAKDOWN'?'3806.67':null,
 observed_close:'3797.24',signal_kind:kind==='TREND_REVERSAL'?'rebound':null,page_parity:true,executable:false,quantity_effect:'none'}
}
test('typed independent display rejects wrong owner, duplicates, future and account semantics',()=>{
 const e=event(),normalize=(v:unknown)=>normalizeDisplayEvents(v,bars,'1d','2026-10-20T00:00:00Z')
 assert.equal(normalize([e])[0]?.event_id,e.event_id)
 for(const invalid of [{...e,physical_contract:'JM2705'},{...e,calculation_segment_id:'other'},{...e,frequency:'1w'},{...e,quantity_effect:'REDUCE'},{...e,source_build_id:null},{...e,known_at:'2026-10-21T00:00:00Z'}])assert.throws(()=>normalize([invalid]))
 assert.throws(()=>normalize([e,e]));assert.deepEqual(normalize([]),[])
})
test('source pill width, 4px offset, three 17px shifts and inclusive final J',()=>{
 const points=[0,1,2,3,4].map(i=>({event:event(i),x:50,y:100}))
 const labels=layoutDisplayLabels(points,()=>53.4)
 assert.deepEqual(labels.map(p=>[p.width,p.y]),[[65,104],[65,121],[65,138],[65,155],[65,155]])
 assert.equal(labels[0]?.label,'↓破位3797.24')
 const mixed=layoutDisplayLabels([{event:event(4,'MAIN_RISE_J'),x:360,y:80},...points],()=>53.4)
 assert.equal(mixed[0]?.y,77);assert.equal(mixed[0]?.label,'J')
 const calls:unknown[][]=[]
 const ctx=new Proxy({},{set:(o,k,v)=>{calls.push(['set',k,v]);return true},get:(_o,k)=>(...a:unknown[])=>calls.push([k,...a])}) as CanvasRenderingContext2D
 drawDisplayLabels(ctx,mixed,true)
 assert.ok(calls.some(c=>c[0]==='strokeText'&&c[1]==='J'&&c[3]===77))
 assert.ok(calls.some(c=>c[0]==='roundRect'&&c[3]===65&&c[4]===16&&c[5]===8))
 assert.ok(calls.some(c=>c[0]==='set'&&c[1]==='strokeStyle'&&c[2]==='rgba(0,0,0,0.78)'))
 calls.length=0;drawDisplayLabels(ctx,mixed,false)
 assert.ok(calls.some(c=>c[0]==='set'&&c[1]==='strokeStyle'&&c[2]==='rgba(255,255,255,0.92)'))
})
test('badge uses current period Bars, expires after two and never crosses owner',()=>{
 assert.equal(trendReversalBadge([event(4,'TREND_REVERSAL')],bars)?.state,'active')
 assert.equal(trendReversalBadge([event(3,'TREND_REVERSAL')],bars)?.state,'gone')
 assert.match(trendReversalBadge([event(2,'TREND_REVERSAL')],bars)!.title,/已于 2026-10-13 消失/)
 assert.equal(trendReversalBadge([event(1,'TREND_REVERSAL')],bars),null)
 assert.equal(trendReversalBadge([event(3,'TREND_REVERSAL')],[...bars.slice(0,4),{...bar(4),calculation_segment_id:'new'}]),null)
 assert.equal(trendReversalBadge([],[]),null)
})

test('logical window includes partially visible edge and final Bar',()=>{
 assert.equal(displayIndexVisible(0,{from:.4,to:3.4}),true)
 assert.equal(displayIndexVisible(4,{from:.4,to:3.4}),true)
 assert.equal(displayIndexVisible(5,{from:.4,to:3.4}),false)
})
