import assert from 'node:assert/strict'
import test from 'node:test'
import { createSessionResources, createReadQueue } from '../src/utils/newowSessionResources.ts'

const tick = () => new Promise(resolve => setImmediate(resolve))

test('last consumer leaving cancels work and late responses cannot enter cache', async () => {
  const store = createSessionResources(), consumer = new AbortController()
  let finish!: (value: string) => void, owner!: AbortSignal
  const result = store.load('obsolete', signal => { owner = signal; return new Promise<string>(resolve => { finish = resolve }) }, String, consumer.signal)
  await tick(); consumer.abort()
  await assert.rejects(result, { name: 'AbortError' })
  assert.equal(owner.aborted, true)
  finish('late'); await tick()
  assert.equal(store.peek('obsolete'), undefined)
  assert.equal(store.stats().pending, 0)
})

test('current validation bypasses a TTL body but still coalesces concurrent readers', async () => {
  const store = createSessionResources()
  store.put('section', 'old-input', String('old'))
  let calls = 0, finish!: (value: string) => void
  const read = () => { calls++; return new Promise<string>(resolve => { finish = resolve }) }
  const first = store.load('section', read, String, undefined, true)
  const second = store.load('section', read, String, undefined, true)
  await tick(); assert.equal(calls, 1)
  finish('verified-input')
  assert.deepEqual(await Promise.all([first, second]), ['verified-input', 'verified-input'])
  assert.equal(store.peek('section'), 'verified-input')
})

test('navigation detaches one consumer while a shared request continues and reuses its result', async () => {
  const store = createSessionResources(), first = new AbortController()
  let calls = 0, resolve!: (value: { token: string }) => void, underlying!: AbortSignal
  const fetch = (signal: AbortSignal) => { calls++; underlying = signal; return new Promise<{ token: string }>(done => { resolve = done }) }
  const old = store.load('chart:owner', fetch, value => value.token, first.signal)
  const resumed = store.load('chart:owner', fetch, value => value.token)
  await tick(); first.abort(); await assert.rejects(old, { name: 'AbortError' })
  assert.equal(underlying.aborted, false)
  resolve({ token: 'a' }); assert.deepEqual(await resumed, { token: 'a' })
  assert.deepEqual(await store.load('chart:owner', fetch, value => value.token), { token: 'a' })
  assert.equal(calls, 1)
})

test('refresh revokes admission even when the old transport ignores cancellation', async () => {
  const store = createSessionResources()
  let oldResolve!: (value: string) => void
  const old = store.load('chart:owner', () => new Promise<string>(done => { oldResolve = done }), String)
  await tick(); store.invalidate('chart:')
  await store.load('chart:owner', async () => 'new', String)
  oldResolve('old'); await old
  assert.equal(store.peek('chart:owner'), 'new')
})

test('TTL is not extended by reads; LRU and byte limits bound all retained ownership', async () => {
  let clock = 0
  const store = createSessionResources({ maxEntries: 2, maxBytes: 100, ttl: 5, now: () => clock })
  store.put('a', '1', 'v1'); store.put('b', '2', 'v1'); store.peek('a'); store.put('c', '3', 'v1')
  assert.equal(store.peek('b'), undefined)
  clock = 4; assert.equal(store.peek('a'), '1'); clock = 5; assert.equal(store.peek('a'), undefined)
  store.put('huge', 'x'.repeat(101), 'v1'); assert.equal(store.peek('huge'), undefined)
  assert.ok(store.stats().bytes <= 100)
})

test('failed requests are retryable and mutations cannot corrupt shared facts', async () => {
  const store = createSessionResources()
  await assert.rejects(store.load('a', async () => { throw Error('offline') }, String))
  await store.load('a', async () => ({ state: 'HOLD' }), JSON.stringify)
  const copy = store.peek<{ state: string }>('a')!; copy.state = 'FLAT'
  assert.equal(store.peek<{ state: string }>('a')!.state, 'HOLD')
})

test('full owner keys isolate contracts, revisions, formula versions and windows', async () => {
  const store = createSessionResources()
  let calls = 0
  const owners = ['contract1:rev1:formula1:window1', 'contract2:rev1:formula1:window1', 'contract1:rev2:formula1:window1', 'contract1:rev1:formula2:window1', 'contract1:rev1:formula1:window2']
  for (const owner of owners) await store.load(owner, async () => ++calls, String)
  assert.equal(calls, owners.length)
})

test('home admission caps recovery plus ordinary reads at two and cancels waiting owners', async () => {
  const queue = createReadQueue(2), signal = new AbortController(), cancelled = new AbortController()
  let active = 0, maximum = 0
  const fetch = async () => { maximum = Math.max(maximum, ++active); await tick(); active--; return 'ok' }
  const tasks = [queue(fetch, signal.signal), queue(fetch, signal.signal)]
  const skipped = queue(fetch, cancelled.signal); cancelled.abort()
  await assert.rejects(skipped, { name: 'AbortError' })
  tasks.push(queue(fetch, signal.signal)); await Promise.all(tasks)
  assert.equal(maximum, 2)
})
