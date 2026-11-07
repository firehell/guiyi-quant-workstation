import test from 'node:test'
import assert from 'node:assert/strict'
import { createHomeProjectionReadLoop } from '../src/utils/homeProjectionReadLoop.ts'
const flush = () => new Promise<void>(resolve => setImmediate(resolve))
function harness() {
  const requests: Array<{ signal: AbortSignal; resolve: (value: boolean) => void; reject: (reason: unknown) => void }> = []
  const accepted: boolean[] = [], errors: string[] = []
  let timer: { callback: () => void; delay: number } | undefined
  const loop = createHomeProjectionReadLoop({
    read: (signal: AbortSignal) => new Promise<boolean>((resolve, reject) => requests.push({ signal, resolve, reject })),
    accept: value => accepted.push(value), failed: kind => errors.push(kind), pending: value => !value,
    schedule(callback, delay) { assert.equal(timer, undefined); timer = { callback, delay }; return 1 as unknown as ReturnType<typeof setTimeout> },
    cancel() { timer = undefined },
  })
  return { loop, requests, accepted, errors, delay: () => timer?.delay, tick() { assert.ok(timer); const fn = timer.callback; timer = undefined; fn() } }
}
test('network failures back off to 60 seconds and success resets; healthy reads continue', async () => {
  const h = harness(); h.loop.setActive(true)
  for (const delay of [2000, 5000, 15000, 30000, 60000, 60000]) { h.requests.at(-1)!.reject(Error('offline')); await flush(); assert.equal(h.delay(), delay); h.tick() }
  h.requests.at(-1)!.resolve(true); await flush(); assert.equal(h.delay(), 60000); h.tick()
  h.requests.at(-1)!.reject(Error('offline')); await flush(); assert.equal(h.delay(), 2000)
  h.loop.dispose()
})
test('nonready reads never exhaust after five minutes', async () => {
  const h = harness(); h.loop.setActive(true)
  for (let i = 0; i < 65; i++) { h.requests.at(-1)!.resolve(false); await flush(); assert.equal(h.delay(), 10000); h.tick() }
  h.loop.dispose()
})
test('hide cancels and late old responses cannot publish; return waits for prior request settlement', async () => {
  const h = harness(); h.loop.setActive(true); h.loop.setActive(false)
  assert.equal(h.requests[0]!.signal.aborted, true); assert.equal(h.delay(), undefined)
  h.loop.setActive(true); assert.equal(h.requests.length, 1)
  h.requests[0]!.resolve(false); await flush(); assert.deepEqual(h.accepted, []); assert.deepEqual(h.errors, []); assert.equal(h.requests.length, 2)
  h.requests[1]!.resolve(true); await flush(); assert.deepEqual(h.accepted, [true])
  h.loop.dispose(); assert.equal(h.delay(), undefined)
})
test('refresh and online do not overlap requests and dispose suppresses late completion', async () => {
  const h = harness(); h.loop.setActive(true); h.loop.refresh(); h.loop.wake()
  assert.equal(h.requests.length, 1); h.requests[0]!.reject(Error('canceled')); await flush(); assert.equal(h.requests.length, 2)
  h.loop.dispose(); h.requests[1]!.resolve(true); await flush(); assert.deepEqual(h.accepted, []); assert.deepEqual(h.errors, [])
})
test('authentication failures stop automatic retries; explicit refresh can recover', async () => {
  for (const status of [401, 403]) {
    const h = harness(); h.loop.setActive(true); h.requests[0]!.reject({ response: { status } }); await flush()
    assert.deepEqual(h.errors, ['access']); assert.equal(h.delay(), undefined)
    h.loop.setActive(false); h.loop.setActive(true); h.loop.wake(); assert.equal(h.requests.length, 1)
    h.loop.refresh(); assert.equal(h.requests.length, 2); h.loop.dispose()
  }
})
test('protocol failures preserve accepted values and retry at low frequency', async () => {
  const h = harness(); h.loop.setActive(true); h.requests[0]!.resolve(true); await flush(); h.tick()
  h.requests[1]!.reject(Error('INVALID_HOME_PROJECTION')); await flush()
  assert.deepEqual(h.accepted, [true]); assert.deepEqual(h.errors, ['protocol']); assert.equal(h.delay(), 60000)
  h.loop.dispose()
})
