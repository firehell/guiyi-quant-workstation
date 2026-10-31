import assert from 'node:assert/strict'
import test from 'node:test'
import {newowProcessHintDisplay,layoutMainRiseProcessLabels,drawMainRiseProcessLabels,MAIN_RISE_LABEL_FONT,type PositionedProcessHint} from '../src/utils/newowProcessHintDisplay.ts'
import type { NewowProductChartBar, NewowProductHintMarker } from '../src/components/market/detail/newow/newowProductChartPrimitives.ts'

const bar: NewowProductChartBar = {
  barEnd: '2026-10-09T07:00:00Z', tradingDay: '2026-10-09',
  open: 110, high: 120, low: 100, close: 115, volume: 100,
  physicalContract: 'JM2611', segmentId: 'owner', calculationSegmentId: 'owner', sourceIdentity: 'revision',
}
const hint: NewowProductHintMarker = {
  id: 'stable-id', kind: 'MAGIC11:4低', barEnd: bar.barEnd, tradingDay: bar.tradingDay,
  value: 100, anchorPrice: '100', confirmedAt: bar.barEnd,
  sourceIdentity: bar.sourceIdentity, formulaVersions: ['newow_magic11_page_v1'],
  physicalContract: bar.physicalContract, segmentId: bar.segmentId, sequence: 0, tone: 'cycle',
}

test('cycle labels use source colors and price placement without modifying signal facts', () => {
  assert.deepEqual(newowProcessHintDisplay(hint, bar), {
    text: '4低', color: '#E53935', below: true, cycle: true, displayPrice: 99, padding: 4,
  })
  assert.equal(hint.anchorPrice, '100')
  for (const [kind, text, color, below] of [
    ['MAGIC11:4高', '4高', '#4CAF50', false], ['MAGIC11:7高', '7高', '#4CAF50', false],
    ['MAGIC11:7低', '7低', '#F5A623', true], ['MAGIC11:11变', '11变', '#E91E63', false],
    ['J', 'J', '#00FF00', false], ['D4', '★B', '#E53935', true],
    ['D5', '★B', '#4CAF50', true], ['D6', '★B', '#2979FF', true],
    ['NEWOW_ESCAPE_D1', '★S逃命', '#E53935', false], ['NEWOW_ESCAPE_D2', '★S逃', '#4CAF50', false],
    ['NEWOW_ESCAPE_D3', '★S跑', '#2979FF', false],
  ] as const) {
    const display = newowProcessHintDisplay({ ...hint, kind }, bar)!
    assert.equal(display.text, text); assert.equal(display.color, color); assert.equal(display.below, below)
    assert.equal(display.displayPrice, below ? 99 : 120)
  }
})

test('unknown, missing and conflicting hint owners are never painted onto another candle', () => {
  for (const change of [
    { kind: 'UNKNOWN' }, { anchorPrice: null }, { value: null }, { value: NaN },
    { physicalContract: 'JM2701' }, { barEnd: 'other' }, { segmentId: 'other' }, { sourceIdentity: 'old' },
  ]) assert.equal(newowProcessHintDisplay({ ...hint, ...change }, bar), null)
})

const point=(id:string,kind:string,x=100,y=100,below=false):PositionedProcessHint=>({id,kind,x,y,below,barEnd:'2026-10-01T07:00:00Z',text:kind==='J'?'J':'label',color:'#00FF00',...(kind.startsWith('MAGIC11')?{cycle:true}:{})})
test('public source 12px stacking shares TA and cycle slots; J draws last without consuming a slot',()=>{
 const inputs=[point('j','J'),point('cycle','MAGIC11:4高'),point('d2','NEWOW_ESCAPE_D2'),point('d1','NEWOW_ESCAPE_D1')]
 const copy=structuredClone(inputs),out=layoutMainRiseProcessLabels(inputs)
 assert.deepEqual(out.map(p=>[p.id,p.y]),[['d1',100],['d2',88],['cycle',76],['j',100]])
 assert.deepEqual(inputs,copy,'layout never mutates hint or coordinate facts')
})
test('public source bounded overflow, strict collision edges and low-side stacking',()=>{
 const dense=Array.from({length:5},(_,i)=>point(String(i),'D4',100,100,true))
 assert.deepEqual(layoutMainRiseProcessLabels(dense).map(p=>p.y),[100,112,124,136])
 assert.deepEqual(layoutMainRiseProcessLabels([point('a','D4'),point('b','D4',112),point('c','D4',100,111)]).map(p=>p.y),[100,100,111])
 assert.equal(layoutMainRiseProcessLabels([point('bad','D4',NaN)]).length,0)
 assert.equal(layoutMainRiseProcessLabels(dense).length,4,'fifth label stays in hint list but has no canvas slot')
})
test('same visible input yields deterministic projection and source Canvas typography in both themes',()=>{
 const p=[point('a','NEWOW_ESCAPE_D1'),point('b','D4',200,120,true)]
 assert.deepEqual(layoutMainRiseProcessLabels(p),layoutMainRiseProcessLabels(p))
 for(const dark of [false,true]){
  const calls:unknown[][]=[]
  const ctx=new Proxy({},{set:(_o,k,v)=>{calls.push(['set',k,v]);return true},get:(_o,k)=>(...a:unknown[])=>calls.push([k,...a])}) as CanvasRenderingContext2D
  drawMainRiseProcessLabels(ctx,p,dark)
  assert.ok(calls.some(c=>c[0]==='set'&&c[1]==='font'&&c[2]===MAIN_RISE_LABEL_FONT))
  assert.ok(calls.some(c=>c[0]==='set'&&c[1]==='lineWidth'&&c[2]===2.4))
  assert.ok(calls.some(c=>c[0]==='set'&&c[1]==='strokeStyle'&&c[2]===(dark?'rgba(0,0,0,0.78)':'rgba(255,255,255,0.92)')))
  assert.deepEqual(calls.filter(c=>c[0]==='set'&&c[1]==='textBaseline').map(c=>c[2]),['bottom','top'])
  assert.equal(calls.filter(c=>c[0]==='fillText').length,2)
 }
})
