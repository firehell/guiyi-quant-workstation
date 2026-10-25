import test from 'node:test'
import assert from 'node:assert/strict'
import { createForwardPanelCache } from '../src/utils/forwardPanelCache.ts'
test('success TTL, key isolation, capacity and failed reads are not cached', async () => {
  let clock = 0, calls = 0
  const cache = createForwardPanelCache<{ n: number }>(10, 1, () => clock)
  const read = async () => ({ n: ++calls })
  const signal = new AbortController().signal
  const first = await cache.load('one', read, signal); first.n = 100
  assert.equal((await cache.load('one', read, signal)).n, 1)
  clock = 11
  assert.equal((await cache.load('one', read, signal)).n, 2)
  await cache.load('two', read, signal)
  assert.equal((await cache.load('one', read, signal)).n, 4)
  let failures = 0
  const fail = async () => { failures++; throw Error('no') }
  await assert.rejects(cache.load('bad', fail, signal))
  await assert.rejects(cache.load('bad', fail, signal))
  assert.equal(failures, 2)
})
test('shared inflight survives cancellation of one caller', async () => {
  const cache = createForwardPanelCache<number>()
  let release!: (value: number) => void, calls = 0
  let shared!: AbortSignal
  const read = async (signal: AbortSignal) => { shared = signal; calls++; return new Promise<number>(resolve => { release = resolve }) }
  const a = new AbortController(), b = new AbortController()
  const first = cache.load('same', read, a.signal)
  const second = cache.load('same', read, b.signal)
  await Promise.resolve(); a.abort()
  await assert.rejects(first, { name: 'AbortError' })
  assert.equal(shared.aborted, false)
  release(42)
  assert.equal(await second, 42)
  assert.equal(calls, 1)
})
