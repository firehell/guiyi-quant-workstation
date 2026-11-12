import assert from 'node:assert/strict'
import test from 'node:test'
import { referencePriceLevelSegments } from '../src/utils/referencePriceLevels.ts'
const bars=['09:45','09:50','09:55','10:00'].map((time,index)=>({time:`2026-10-19T${time}:00+08:00`,physicalContract:'JM2701',calculationSegmentId:index===3?'owner2':'owner1',open:100,high:101,low:99,close:100,volume:20}))
const points=bars.map(bar=>({bar_end:bar.time,physical_contract:'JM2701',segment_id:bar.calculationSegmentId,owner_segment_id:bar.calculationSegmentId,reference_side:'LONG' as const,target_reference_price:'110.25',stop_reference_price:'95.50',dif:null,dea:null,macd:null,ema21:null}))
test('reference price levels preserve server values and split missing, flat and owner boundaries',()=>{
  const segments=referencePriceLevelSegments(bars,points)
  assert.deepEqual(segments.filter(s=>s.kind==='target').map(s=>s.points.length),[3,1])
  assert.equal(segments[0]?.points[0]?.value,110.25)
  const interrupted=structuredClone(points);interrupted[1]!.reference_side='FLAT' as any
  assert.deepEqual(referencePriceLevelSegments(bars,interrupted).filter(s=>s.kind==='target').map(s=>s.points.length),[1,1,1])
  interrupted[2]!.physical_contract='JM2609';assert.equal(referencePriceLevelSegments(bars,interrupted).filter(s=>s.kind==='target').length,2)
})
