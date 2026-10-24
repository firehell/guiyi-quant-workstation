import assert from 'node:assert/strict'
import test from 'node:test'
import { historicalActionCallouts } from '../src/utils/historicalActionCallouts.ts'
import { useHistoricalSignalRanges } from '../src/composables/useHistoricalSignalRanges.ts'
import type { HistoricalChartAction } from '../src/types/historicalChartAction.ts'
const identity = {symbol:'jm',strategy:'htdy',frequency:'15m'}
const bar = {time:'2026-10-23T07:00:00Z',trading_day:'2026-10-23',physicalContract:'JM2701',calculationSegmentId:'calc',open:1,high:1,low:1,close:1,volume:1}
const action: HistoricalChartAction = {action_id:'entry',reference_trade_id:'trade',signal_id:'signal',role:'BUILD',side:'LONG',bar_end:bar.time,trading_day:bar.trading_day,physical_contract:bar.physicalContract,segment_id:'owner',calculation_segment_id:'calc',reference_price:'1400',return_pct:null,status:'CLOSED',recording_mode:'historical_replay'}
test('reversal retains two exact actions, clear return colors and build side without recalculating',()=>{
 const result=historicalActionCallouts([{...action,action_id:'exit',role:'CLEAR',side:'SHORT',return_pct:'-0.52'},{...action,reference_trade_id:'next'}],[bar])
 assert.deepEqual(result.map(x=>x.title),['清仓·空','建仓·多'])
 assert.equal(result[0].tone,'loss'); assert.equal(result[0].detail,'1400.00(-0.52%)')
 assert.equal(result[1].tone,'neutral'); assert.equal(result[1].detail,'建仓价:1400.00')
 assert.equal(historicalActionCallouts([{...action,role:'CLEAR',return_pct:'1.5'}],[bar])[0].tone,'gain')
})
test('rejects wrong physical and calculation owner, deduplicates stable action and marks interruption',()=>{
 assert.deepEqual(historicalActionCallouts([{...action,physical_contract:'JM2609'},{...action,calculation_segment_id:'other'}],[bar]),[])
 assert.equal(historicalActionCallouts([action,action],[bar]).length,1)
 assert.match(historicalActionCallouts([{...action,status:'ROLLOVER_INTERRUPTED'}],[bar])[0].title,/换月中断/)
 assert.equal(historicalActionCallouts([{...action,role:'CLEAR',status:'OPEN',return_pct:'99'}],[bar])[0].tone,'neutral')
})
for(const failure of ['network','SOURCE_CHANGED']) test(`${failure} preserves or revokes accepted actions correctly`,async()=>{
 let fail=false
 const state=useHistoricalSignalRanges(async query=>{
  if(fail) throw new Error(failure)
  return {...query,identity,sourceToken:'s',signals:[],actions:[action],nextCursor:null}
 })
 await state.sync(identity,[bar]); assert.equal(state.actions.value.length,1)
 fail=true
 await state.sync(identity,[bar,{...bar,time:'2026-10-23T07:15:00Z'}])
 assert.equal(state.actions.value.length,failure==='network'?1:0)
 assert.ok(state.error.value);state.dispose()
})
test('actions across paginated reversal and overlapping chunks deduplicate by stable identity',async()=>{
 const state=useHistoricalSignalRanges(async query=>({...query,identity,sourceToken:'s',signals:[],actions:query.before?[{...action,action_id:'exit',role:'CLEAR',side:'SHORT',return_pct:'1'}]:[action],nextCursor:query.before?null:'next'}))
 await state.sync(identity,[bar]);assert.deepEqual(state.actions.value.map(x=>x.action_id),['entry','exit']);state.dispose()
})
