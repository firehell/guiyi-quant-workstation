import assert from 'node:assert/strict'
import test from 'node:test'
import { referencePriceLevelSegments } from '../src/utils/referencePriceLevels.ts'
import { futuresReferenceIndicators } from '../src/utils/newowFuturesSnapshot.ts'
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
test('futures frame display adapter uses exact owned bars, only LONG/SHORT, and explicit independent toggles',()=>{
  const packet={chart:{bars:bars.map(bar=>({bar_end:bar.time,physical_contract:bar.physicalContract,owner_segment_id:bar.calculationSegmentId})),frames:[{bar_end:bars[0]!.time,side:'LONG',target_reference_price:'110.25',stop_reference_price:'95.50'},{bar_end:bars[1]!.time,side:'UNAVAILABLE',target_reference_price:'110.25',stop_reference_price:'95.50'},{bar_end:bars[2]!.time,side:'SHORT',target_reference_price:'90.25',stop_reference_price:'105.50'}]}}
  const all=futuresReferenceIndicators(packet as any,true,true)
  assert.equal(all.length,2);assert.equal(all[0]?.owner_segment_id,'owner1');assert.equal(all[0]?.ema21,null)
  assert.equal(futuresReferenceIndicators(packet as any,false,true)[0]?.target_reference_price,null)
  assert.equal(futuresReferenceIndicators(packet as any,true,false)[0]?.stop_reference_price,null)
})
