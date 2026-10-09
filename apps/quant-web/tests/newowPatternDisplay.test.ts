import assert from 'node:assert/strict'
import test from 'node:test'
import { splitNewowPatternOwners, PatternScanSession, buildNewowPatternGeometry } from '../src/utils/newowPatternDisplay.ts'
const bars = Array.from({length:45},(_,i)=>({barEnd:`2026-09-${String(i+1).padStart(2,'0')}`,tradingDay:'2026-09-01',open:100,high:102,low:98,close:100,volume:100,physicalContract:'RB2701',segmentId:'a',calculationSegmentId:'calc',sourceIdentity:`s${i}`}))
test('pattern inputs never join separate owners or a returning calculation segment',()=>{
 const groups=splitNewowPatternOwners([...bars.slice(0,2),{...bars[2]!,physicalContract:'RB2705'},...bars.slice(3,5)])
 assert.deepEqual(groups.map(g=>g.bars.length),[2,1,2]);assert.notEqual(groups[0]!.key,groups[2]!.key)
})
test('cancelled pattern workers cannot repaint a different snapshot',()=>{
 const ports:any[]=[];const done:any[]=[]
 const session=new PatternScanSession(()=>{const p={onmessage:null,onerror:null,terminate(){this.stopped=true},postMessage(){},stopped:false};ports.push(p);return p},m=>done.push(m))
 session.run({key:'old',period:'day',groups:splitNewowPatternOwners(bars)})
 const stale=ports[0].onmessage
 session.run({key:'new',period:'week',groups:splitNewowPatternOwners(bars)})
 stale({data:{key:'old',results:[],error:null}})
 ports[1].onmessage({data:{key:'new',results:[],error:null}})
 assert.deepEqual(done.map(d=>d.key),['new']);assert.equal(ports[0].stopped,true)
 session.cancel();assert.equal(ports[1].stopped,true)
})
test('platform outline uses exact returned index and price boundaries',()=>{
 const g=buildNewowPatternGeometry({pattern:{type:'flat-base',score:85,params:{startIdx:25,endIdx:44,upperPrice:102,lowerPrice:98}},bars},'1d')
 assert.equal(g.lines[0]!.points[0]!.barEnd,bars[25]!.barEnd);assert.equal(g.lines[0]!.points[2]!.price,98);assert.equal(g.lines[1]!.dashed,true);assert.match(g.label,/平台.*85/)
})
test('double bottom without breakout never draws an invented future bar',()=>{
 const g=buildNewowPatternGeometry({pattern:{type:'double-bottom',score:75,params:{bottom1Idx:5,bottom2Idx:25,neckLinePrice:110,baseDays:20,breakoutIdx:-1}},bars},'60m')
 assert.ok(g.lines.every(l=>l.points.every(p=>bars.some(b=>b.barEnd===p.barEnd))));assert.ok(g.anchors.some(a=>a.label==='底1'));assert.ok(g.anchors.some(a=>a.label==='底2'))
})
test('invalid indices fail closed instead of clipping to a different bar',()=>{
 assert.throws(()=>buildNewowPatternGeometry({pattern:{type:'flat-base',score:85,params:{startIdx:-1,endIdx:100,upperPrice:102,lowerPrice:98}},bars},'1d'),/index/)
})

test('pattern primitive paints time/price lines and stops after detachment', async()=>{
 const {NewowPublicPatternPrimitive}=await import('../src/components/market/detail/newow/newowPublicPatternPrimitive.ts')
 const primitive=new NewowPublicPatternPrimitive();const lines:number[][]=[]
 const ctx:any={save(){},restore(){},beginPath(){},setLineDash(){},moveTo(x:number,y:number){lines.push([x,y])},lineTo(x:number,y:number){lines.push([x,y])},stroke(){},arc(){},fill(){},fillText(){}}
 primitive.attached({chart:{timeScale:()=>({timeToCoordinate:()=>10})},series:{priceToCoordinate:(p:number)=>p},requestUpdate(){}} as any)
 primitive.setData({label:'平台',frequency:'1d',lines:[{dashed:false,points:[{barEnd:'2026-09-01T07:00:00Z',tradingDay:'2026-09-01',price:102},{barEnd:'2026-09-02T07:00:00Z',tradingDay:'2026-09-02',price:98}]}],anchors:[]})
 const target:any={useMediaCoordinateSpace(fn:any){fn({context:ctx,mediaSize:{width:200,height:200}})}}
 primitive.paneViews()[0]!.renderer()!.draw(target)
 assert.deepEqual(lines,[[10,102],[10,98]])
 primitive.detached();primitive.paneViews()[0]!.renderer()!.draw(target);assert.equal(lines.length,2)
})
