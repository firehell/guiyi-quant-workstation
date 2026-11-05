import test from 'node:test'
import assert from 'node:assert/strict'
import { subingVolumeTierPoints } from '../src/utils/subingVolumeTierDisplay.ts'
import type { DisplayVolumeBar } from '../src/utils/volumeDisplay.ts'
const bar=(volume:number,time='2026-11-02T07:00:00Z'):DisplayVolumeBar=>({time,open:100,high:110,low:90,close:105,volume,physicalContract:'JM2701',segmentId:'s',calculationSegmentId:'c'})
const pair=(value:number)=>[bar(100),bar(value,'2026-11-03T07:00:00Z')]
test('only the 2x and >=3x tiers are marked with inclusive exact boundaries',()=>{
 for(const [value,tier] of [[0,null],[100,null],[150,null],[199.999,null],[200,2],[299.999,2],[300,3],[900,3]] as const){
  const points=subingVolumeTierPoints(pair(value))
  assert.equal(points[0]?.tier??null,tier)
  if(tier)assert.equal(points[0]!.ratio,value/100)
 }
})
test('always compares the immediate completed predecessor, never a moving average',()=>{
 const bars=[bar(1000,'2026-11-01T07:00:00Z'),...pair(210)]
 assert.equal(subingVolumeTierPoints(bars).at(-1)!.ratio,2.1)
 assert.equal(subingVolumeTierPoints(bars).at(-1)!.previousEnd,bars[1]!.time)
})
test('missing, zero baseline, unconfirmed, time reversal and owner boundaries fail closed',()=>{
 for(const update of [{volume:0},{volume:undefined},{volume:NaN},{volume:-1},{confirmed:false},{physicalContract:'JM2609'},{physicalContract:''},{segmentId:'old'},{calculationSegmentId:'old'},{calculationSegmentId:''},{time:'invalid'},{time:'2026-11-03T07:00:00Z'}]){
  const bars=pair(300);bars[0]={...bars[0]!,...update}
  assert.deepEqual(subingVolumeTierPoints(bars),[],JSON.stringify(update))
 }
 for(const update of [{volume:undefined},{volume:Infinity},{confirmed:false}]){
  const bars=pair(300);bars[1]={...bars[1]!,...update};assert.deepEqual(subingVolumeTierPoints(bars),[])
 }
 const bars=[bar(100),{...bar(100,'2026-11-03T07:00:00Z'),volume:undefined},bar(300,'2026-11-04T07:00:00Z')]
 assert.deepEqual(subingVolumeTierPoints(bars),[],'do not skip missing predecessor')
 assert.deepEqual(subingVolumeTierPoints(pair(300),[{time:'2026-11-02T08:00:00Z'}]),[])
})
test('same classification on all six periods, prefix invariance and stable pagination overlap',()=>{
 for(const frequency of ['5m','15m','30m','60m','1d','1w'])assert.equal(subingVolumeTierPoints(pair(300).map(b=>({...b,frequency})))[0]!.tier,3)
 const bars=[...pair(210),bar(650,'2026-11-04T07:00:00Z')],before=structuredClone(bars)
 assert.deepEqual(subingVolumeTierPoints(bars).slice(0,1),subingVolumeTierPoints(bars.slice(0,2)))
 assert.deepEqual(subingVolumeTierPoints(bars).slice(1),subingVolumeTierPoints(bars.slice(1)))
 assert.deepEqual(bars,before)
})
