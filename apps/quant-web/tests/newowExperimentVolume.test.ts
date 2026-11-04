import test from 'node:test'
import assert from 'node:assert/strict'
import { experimentVolumeBars } from '../src/utils/newowExperimentVolume.ts'
import { volumeColors } from '../src/utils/volumeDisplay.ts'
const source=Array.from({length:10},(_,i)=>({barEnd:`2026-10-${String(i+1).padStart(2,'0')}T07:00:00Z`,physicalContract:'JM2701',segmentId:'owner',calculationSegmentId:'owner|quality-v2',open:90,close:108,high:110,low:90,volume:100}))
const bars=source.map(b=>({bar_end:b.barEnd.replace('Z','+00:00'),trading_day:b.barEnd.slice(0,10),physical_contract:b.physicalContract,segment_id:b.calculationSegmentId,calculation_segment_id:b.calculationSegmentId,open:String(b.open),close:String(b.close),high:String(b.high),low:String(b.low),channel_high:null,channel_low:null}))
test('experiment calculation segment joins exact main-chart volume and has identical colors',()=>{
 const input=experimentVolumeBars(bars,source)
 assert.equal(input[9]!.volume,100);assert.equal(input[9]!.segmentId,'owner')
 assert.deepEqual(volumeColors(input),volumeColors(source))
 assert.equal(volumeColors(input)[9],'#D9A400')
})
test('missing volume, different owner or corrected OHLC cannot borrow source volume',()=>{
 for(const change of [{calculation_segment_id:'other'},{segment_id:'other'},{physical_contract:'JM2609'},{close:'107'},{bar_end:'2026-11-01T07:00:00Z'}]){
  const input=experimentVolumeBars([{...bars[9]!,...change}],source)
  assert.equal(input[0]!.volume,undefined)
 }
 assert.equal(experimentVolumeBars(bars,[])[9]!.volume,undefined)
})

test('unconfirmed source cannot become a yellow historical bar',()=>{
 const input=experimentVolumeBars(bars,source.map(bar=>({...bar,confirmed:false})))
 assert.equal(input[9]!.confirmed,false)
 assert.equal(volumeColors(input)[9],'rgba(255,59,48,0.6)')
})
