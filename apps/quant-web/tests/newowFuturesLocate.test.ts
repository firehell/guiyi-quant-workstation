import assert from 'node:assert/strict'
import test from 'node:test'
import { locateFuturesRecord } from '../src/utils/newowFuturesLocate.ts'
const bars=['09:45','09:50'].map(time=>({bar_end:`2026-10-19T${time}:00+08:00`,physical_contract:'JM2701',owner_segment_id:'owner'}))
const packet={chart:{bars},reference:{actions:[]},run_id:'run',sha256:'sha'} as any

test('trade location requires exact time contract and owner; never selects nearest or last bar',()=>{
  const row={entry_at:bars[0]!.bar_end,exit_at:bars[1]!.bar_end,physical_contract:'JM2701',owner_segment_id:'owner'}
  assert.equal(locateFuturesRecord(packet,row,'entry','trades').kind,'located')
  assert.equal(locateFuturesRecord(packet,{...row,entry_at:'2024-10-19T09:45:00+08:00'},'entry','trades').message,'超出当前冻结图表窗口')
  assert.equal(locateFuturesRecord(packet,{...row,entry_at:'2026-10-19T09:47:00+08:00'},'entry','trades').kind,'unavailable')
  assert.equal(locateFuturesRecord(packet,{...row,physical_contract:'JM2609'},'entry','trades').kind,'unavailable')
  assert.equal(locateFuturesRecord(packet,{...row,owner_segment_id:'other'},'entry','trades').kind,'unavailable')
})
test('reference minute action may use its own verified server display coordinate, never another account record',()=>{
  const row={action_id:'close',at:'2026-10-19T09:47:00+08:00',bar_end:'2026-10-19T09:47:00+08:00',display_bar_end:bars[1]!.bar_end,physical_contract:'JM2701',owner_segment_id:'owner'}
  const p={...packet,reference:{actions:[row]}}
  const located=locateFuturesRecord(p,row,'at','reference-actions')
  assert.equal(located.kind,'located');if(located.kind==='located')assert.equal(located.barEnd,bars[1]!.bar_end)
  assert.equal(locateFuturesRecord(p,row,'at','fills').kind,'unavailable')
})
