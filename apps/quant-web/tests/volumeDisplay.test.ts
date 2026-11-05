import test from 'node:test'
import assert from 'node:assert/strict'
import { volumeColors, volumeScores, validVolume, type VolumeBar } from '../src/utils/volumeDisplay.ts'
function fixture(): VolumeBar[] {
 const bars=Array.from({length:10},()=>({open:100,high:110,low:90,close:100,volume:100,physicalContract:'JM2701',segmentId:'s',calculationSegmentId:'c'}))
 bars[9]={...bars[9]!,open:90,close:108,volume:200};return bars
}
test('both channel sides use one scoring implementation, independent of any action',()=>{
 const bars=fixture(),[lower,upper]=volumeScores(bars,9)
 assert.equal(lower!.total,6);assert.equal(lower!.volumeRatio,200/110);assert.equal(lower!.bodyRatio,.9);assert.equal(lower!.penetrationRatio,18/90)
 assert.equal(upper!.reference,110);assert.equal(upper!.total,5)
 assert.equal(volumeColors(bars)[9],'#D9A400');assert.equal(volumeColors(bars,'dark')[9],'#FFD60A')
 assert.equal(volumeColors(bars)[0],'rgba(255,59,48,0.6)')
 const down=fixture();down[9]={...down[9]!,open:110,close:92};assert.equal(volumeScores(down,9)[1]!.total,6)
})
test('strict body and penetration boundaries, inclusive volume thresholds',()=>{
 const bars=fixture();bars[9]={...bars[9]!,open:102,close:108,low:100,volume:100}
 assert.equal(volumeScores(bars,9)[0]!.bodyScore,1)
 assert.equal(volumeScores(bars,9)[0]!.volumeScore,1)
 bars[9]={...bars[9]!,open:99,close:102,high:105,low:95}
 assert.equal(volumeScores(bars,9)[0]!.bodyScore,0)
 const exact=Array.from({length:10},()=>({...bars[9]!,open:100,close:103,low:100,high:110}))
 assert.equal(volumeScores(exact,9)[0]!.penetrationScore,1)
 exact[9]={...exact[9]!,close:101};assert.equal(volumeScores(exact,9)[0]!.penetrationScore,0)
 exact.forEach(bar=>bar.volume=170);exact[9]!.volume=270
 assert.equal(volumeScores(exact,9)[0]!.volumeRatio,1.5);assert.equal(volumeScores(exact,9)[0]!.volumeScore,2)
})
test('warm-up, each ownership boundary, preview and missing/invalid values fail closed',()=>{
 assert.deepEqual(volumeScores(fixture(),8),[])
 for(const change of [{physicalContract:'JM2609'},{segmentId:'other'},{calculationSegmentId:'other'},{calculationSegmentId:''},{physicalContract:''},{volume:undefined},{volume:NaN},{volume:-1},{confirmed:false},{high:Infinity}]){
  const bars=fixture();bars[5]={...bars[5]!,...change};assert.deepEqual(volumeScores(bars,9),[],JSON.stringify(change))
 }
 const bars=fixture();bars[9]={...bars[9]!,confirmed:false};assert.equal(volumeColors(bars)[9],'rgba(255,59,48,0.6)')
 assert.equal(validVolume({ ...bars[9]!, volume:null }),false)
 assert.equal(volumeColors(fixture(),'light',false)[9],'rgba(255,59,48,0.6)')
})
test('zero volume is retained as fact with the existing neutral ratio fallback',()=>{
 const bars=fixture();for(const bar of bars)bar.volume=0
 assert.equal(validVolume(bars[9]!),true);assert.equal(volumeScores(bars,9)[0]!.volumeRatio,1)
 assert.equal(volumeScores(bars,9)[0]!.volumeScore,1)
})
test('prefix invariance, pagination overlap with sufficient history, adapter parity and immutability',()=>{
 const bars=[...fixture(),...fixture()],before=structuredClone(bars)
 for(let size=1;size<=bars.length;size++)assert.deepEqual(volumeColors(bars.slice(0,size)),volumeColors(bars).slice(0,size))
 assert.deepEqual(volumeColors(bars.slice(5)).slice(9),volumeColors(bars).slice(14))
 for(const strategy of ['trend','oscillation','main_rise','experiment','subing','htdy','free']){
  const adapted=bars.map(bar=>({...bar,strategy}));assert.deepEqual(volumeColors(adapted),volumeColors(bars))
 }
 assert.deepEqual(bars,before)
})
