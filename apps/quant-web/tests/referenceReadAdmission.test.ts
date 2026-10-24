import assert from 'node:assert/strict'
import test from 'node:test'
import { withReferenceRead } from '../src/api/referenceReadAdmission.ts'
test('replay transport is serial and cancelled queued reads never start', async () => {
 let finish!: () => void, active = 0, peak = 0, cancelledStarted = false
 const first = withReferenceRead(async () => { active++; peak=Math.max(peak,active); await new Promise<void>(resolve=>{finish=resolve}); active--; return 1 })
 await new Promise(resolve=>setImmediate(resolve))
 const abort = new AbortController()
 const cancelled = withReferenceRead(async()=>{cancelledStarted=true},abort.signal)
 const rejection = assert.rejects(cancelled,{name:'AbortError'})
 const second = withReferenceRead(async()=>{active++;peak=Math.max(peak,active);active--;return 2})
 abort.abort();finish()
 assert.equal(await first,1);assert.equal(await second,2);await rejection
 assert.equal(peak,1);assert.equal(cancelledStarted,false)
})
