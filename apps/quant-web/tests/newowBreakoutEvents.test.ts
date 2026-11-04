import test from 'node:test'
import assert from 'node:assert/strict'
import {readFileSync} from 'node:fs'
import {normalizeBreakoutEvents,layoutBreakouts,breakoutTitle,breakoutDateLine,BREAKOUT_VERSION,type NewowBreakoutEvent} from '../src/utils/newowBreakoutEvents.ts'
const bars=['2026-11-02T01:00:00Z','2026-11-02T02:00:00Z','2026-11-02T03:00:00Z'].map(bar_end=>({bar_end,physical_contract:'JM2701',segment_id:'s',calculation_segment_id:'c'}))
const event=():NewowBreakoutEvent=>({event_id:'e',display_version:BREAKOUT_VERSION,formula_version:BREAKOUT_VERSION,product:'jm',frequency:'60m',bar_end:bars[1]!.bar_end,known_at:bars[1]!.bar_end,occur_bar_end:bars[0]!.bar_end,confirmed_at:bars[1]!.bar_end,physical_contract:'JM2701',segment_id:'s',calculation_segment_id:'c',kind:'true_up',side:'up',level:'100',buffer:'2',threshold:'102',volume_ratio:'1.3',volume_ok:true,doubt:false,regime:'osc',occur_high:'105',occur_low:'98',confirm_close:'104',bar_gap:1,source_sha256:'a'.repeat(64),input_sha256:'b'.repeat(64),executable:false})
const parse=(raw:unknown)=>normalizeBreakoutEvents(raw,bars,'60m','2026-11-03T00:00:00Z','jm')
test('independent breakout parser binds formula, owner and adjacent confirmation',()=>{
 assert.equal(parse([event()])[0]!.kind,'true_up')
 for(const patch of [{physical_contract:'JM2705'},{calculation_segment_id:'x'},{known_at:'2026-11-04T00:00:00Z'},{confirmed_at:bars[0]!.bar_end},{formula_version:'wrong'},{side:'down'},{product:'rb'},{bar_gap:2},{volume_ratio:'NaN'},{bar_end:bars[2]!.bar_end,confirmed_at:bars[2]!.bar_end,known_at:bars[2]!.bar_end}])assert.throws(()=>parse([{...event(),...patch}]))
 assert.throws(()=>parse([event(),event()]))
})
test('pending and wick facts remain unconfirmed and accept delayed initial knowledge',()=>{
 const pending={...event(),kind:'pending',bar_end:bars[0]!.bar_end,known_at:bars[0]!.bar_end,confirmed_at:null,bar_gap:null,confirm_close:null}
 assert.equal(parse([pending])[0]!.kind,'pending')
 assert.equal(parse([{...pending,kind:'wick_upper',known_at:bars[1]!.bar_end}])[0]!.kind,'wick_upper')
 assert.throws(()=>parse([{...pending,confirmed_at:bars[1]!.bar_end}]))
})
test('shared layout clips viewport, resolves collisions, colors directions and separates wick toggle',()=>{
 const p={event:event(),x:2,y:40}
 const labels=layoutBreakouts([p,{...p,event:{...event(),event_id:'f',kind:'false_up'}},{...p,event:{...event(),event_id:'w',kind:'wick_upper'}},{...p,x:-10}],160,150)
 assert.equal(labels.length,2);assert.notEqual(labels[0]!.top,labels[1]!.top);assert.equal(labels[0]!.color,'#e53935');assert.equal(labels[1]!.color,'#23a85a')
 for(const label of labels)assert.ok(label.left>=0&&label.left+label.width<=160&&label.width<=112&&label.top>=0&&label.top+30<=150)
 assert.equal(layoutBreakouts([{...p,event:{...event(),kind:'wick_upper'}}],160,150,false,true)[0]!.color,'#ed8b20')
 assert.equal(layoutBreakouts([p],160,150,false,false).length,0)
})
test('shared DOM labels retain native keyboard activation and both chart surfaces use the overlay',()=>{
 const source=readFileSync(new URL('../src/components/market/detail/newow/NewowBreakoutOverlay.vue',import.meta.url),'utf8')
 assert.match(source,/type="button"/);assert.match(source,/@click.stop=/);assert.match(source,/:aria-label=/);assert.match(source,/:focus-visible/)
 for(const file of ['NewowExperimentPanel','NewowProductChartStage'])assert.match(readFileSync(new URL('../src/components/market/detail/newow/'+file+'.vue',import.meta.url),'utf8'),/NewowBreakoutOverlay/)
})

test('public capsule semantics retain support pressure, directional pending and occurrence confirmation dates',()=>{
 assert.equal(breakoutTitle(event()),'真突破·转撑');assert.equal(breakoutTitle({...event(),kind:'true_down',side:'down'}),'真跌破·转压')
 assert.equal(breakoutTitle({...event(),kind:'pending',side:'down'}),'跌破待定');assert.equal(breakoutTitle({...event(),kind:'pending'}),'突破待定')
 assert.equal(breakoutTitle({...event(),kind:'wick_upper'}),'上影诱多');assert.equal(breakoutTitle({...event(),kind:'wick_lower'}),'下影诱空')
 assert.match(breakoutDateLine(event()),/11-02 › 11-02/);assert.match(breakoutDateLine({...event(),kind:'pending',confirmed_at:null}),/11-02 › —/);assert.equal(breakoutDateLine({...event(),kind:'wick_upper'}),'11-02')
 const p={event:event(),x:80,y:80},labels=layoutBreakouts(Array.from({length:8},(_,i)=>({...p,event:{...event(),event_id:String(i)}})),160,200)
 assert.ok(labels.length<=4);assert.ok(labels.every(label=>label.height===30&&label.width<=112));for(let i=0;i<labels.length;i++)for(let j=i+1;j<labels.length;j++)assert.ok(Math.abs(labels[i]!.top-labels[j]!.top)>=30)
})
