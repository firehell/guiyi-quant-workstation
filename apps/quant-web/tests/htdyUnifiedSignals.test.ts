import assert from 'node:assert/strict'
import test from 'node:test'
import { htdyReplayMarkers, htdyUnifiedMarkers } from '../src/utils/htdyUnifiedSignals.ts'
const action = {action_id:'a',reference_trade_id:'t',signal_id:'s',role:'BUILD' as const,side:'LONG' as const,bar_end:'2026-10-30T07:00:00Z',trading_day:'2026-10-30',physical_contract:'JM2701',segment_id:'s',calculation_segment_id:'c',reference_price:'1400',return_pct:null,status:'OPEN' as const,recording_mode:'historical_replay' as const}
const bars = [{time:action.bar_end,physicalContract:'JM2701',open:1400,high:1401,low:1399,close:1400,volume:1}]
test('frozen actions require exact physical ownership and never use final repaint signals',()=>{
 assert.equal(htdyReplayMarkers([action],bars,'snapshot').length,1)
 assert.equal(htdyReplayMarkers([action],[{...bars[0]!,physicalContract:'JM2609'}],'snapshot').length,0)
})
test('unknown observed formula and conflicts remain alongside replay, never erase it',()=>{
 const replay=htdyReplayMarkers([action],bars,'snapshot')
 const observed={strategy:'htdy',frequency:'60m',barEnd:action.bar_end,physicalContract:'JM2701',source:'actual_observation' as const,marker:{id:'observed:1',time:action.bar_end,label:'买观察',tone:'up' as const,position:'aboveBar' as const,shape:'square' as const}}
 const combined=htdyUnifiedMarkers(replay,[observed],['v1'])
 assert.equal(combined.length,2)
 assert.match(combined[1]!.tooltip!,/版本未确认/)
})
test('verified same-version evidence takes visual priority without altering reference actions',()=>{
 const replay=htdyReplayMarkers([action],bars,'snapshot')
 const observed={strategy:'htdy',frequency:'60m',barEnd:action.bar_end,physicalContract:'JM2701',historicalSignalId:'s',formulaVersion:'v1',source:'actual_observation' as const,marker:{id:'observed:1',time:action.bar_end,label:'买观察',tone:'up' as const,position:'aboveBar' as const,shape:'square' as const}}
 assert.equal(htdyUnifiedMarkers(replay,[observed],['v1']).length,1)
 assert.equal(action.reference_price,'1400')
})

test('formula/time/contract agreement alone never fabricates a stable cross-source association',()=>{
 const replay=htdyReplayMarkers([action],bars,'snapshot')
 const observed={strategy:'htdy',frequency:'60m',barEnd:action.bar_end,physicalContract:'JM2701',formulaVersion:'v1',source:'actual_observation' as const,marker:{id:'event:1',time:action.bar_end,label:'买观察',tone:'up' as const,position:'aboveBar' as const,shape:'square' as const}}
 assert.equal(htdyUnifiedMarkers(replay,[observed],['v1']).length,2)
 assert.equal(htdyUnifiedMarkers(replay,[{...observed,historicalSignalId:'foreign'}],['v1']).length,2)
})

test('conflicting associated actual records never remove replay history',()=>{
 const replay=htdyReplayMarkers([action],bars,'snapshot')
 const base={strategy:'htdy',frequency:'60m',barEnd:action.bar_end,physicalContract:'JM2701',historicalSignalId:'s',formulaVersion:'v1',source:'actual_observation' as const}
 const marker={id:'event:1',time:action.bar_end,label:'买观察',tone:'up' as const,position:'aboveBar' as const,shape:'square' as const}
 assert.equal(htdyUnifiedMarkers(replay,[{...base,marker},{...base,marker:{...marker,id:'event:2',tone:'down'}}],['v1']).length,3)
})
