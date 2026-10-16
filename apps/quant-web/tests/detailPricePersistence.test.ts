import assert from 'node:assert/strict'
import test from 'node:test'
import { createDetailPriceDiskCache, type DetailPriceEntry, type DetailPriceStorage } from '../src/utils/detailPricePersistence.ts'

function storage() {
  const rows = new Map<string, unknown>()
  const reads: string[] = [], writes: string[] = [], deletes: string[] = []
  let tail = Promise.resolve()
  const adapter: DetailPriceStorage = {
    transact(key, change) {
      const result = tail.then(() => {
        reads.push('__meta__', key)
        const mutation = change(structuredClone(rows.get('__meta__')), structuredClone(rows.get(key)))
        for (const removed of mutation.removals ?? []) { rows.delete(removed); deletes.push(removed) }
        if (mutation.entry) { rows.set(mutation.entry.key, structuredClone(mutation.entry)); writes.push(mutation.entry.key) }
        if (mutation.index) { rows.set(mutation.index.key, structuredClone(mutation.index)); writes.push(mutation.index.key) }
        return mutation.result
      })
      tail = result.then(() => undefined, () => undefined)
      return result
    },
  }
  return { adapter, rows, reads, writes, deletes }
}

test('detail prices read by key and evict least recently used rows within a disk budget', async () => {
  let clock = 1
  const store = storage()
  const cache = createDetailPriceDiskCache(store.adapter, { now: () => clock, maxBytes: 400, timeoutMs: 1000 })
  await cache.put('price:a', 'a'.repeat(30))
  clock++
  await cache.put('price:b', 'b'.repeat(30))
  clock++
  assert.equal(await cache.get('price:a', String), 'a'.repeat(30))
  clock++
  await cache.put('price:c', 'c'.repeat(30))
  assert.equal(await cache.get('price:b', String), undefined)
  assert.equal(await cache.get('price:a', String), 'a'.repeat(30))
  assert.ok(cache.stats().bytes <= 400)
  assert.ok(store.deletes.includes('price:b'))
  assert.deepEqual(store.reads.slice(0, 2), ['__meta__', 'price:a'])
  assert.ok(store.writes.every(key => key === '__meta__' || key.startsWith('price:')))
})

test('two cache instances merge against current metadata and never orphan a live row', async () => {
  let clock = 1
  const store = storage()
  const first = createDetailPriceDiskCache(store.adapter, { now: () => clock, maxBytes: 400, timeoutMs: 1000 })
  const second = createDetailPriceDiskCache(store.adapter, { now: () => clock, maxBytes: 400, timeoutMs: 1000 })
  await first.put('price:a', 'a'.repeat(30))
  clock++
  await second.put('price:b', 'b'.repeat(30))
  clock++
  assert.equal(await first.get('price:a', String), 'a'.repeat(30))
  clock++
  await second.put('price:c', 'c'.repeat(30))
  assert.equal(await first.get('price:b', String), undefined)
  assert.equal(await second.get('price:a', String), 'a'.repeat(30))
  const index = store.rows.get('__meta__') as { entries: Array<{ key: string }> }
  assert.deepEqual([...store.rows.keys()].filter(key => key !== '__meta__').sort(), index.entries.map(item => item.key).sort())
})

test('expired, mismatched, and invalid bodies never restore as price facts', async () => {
  let clock = 10
  const store = storage()
  const cache = createDetailPriceDiskCache(store.adapter, { now: () => clock, maxAgeMs: 7, timeoutMs: 1000 })
  await cache.put('price:old', { value: 1 })
  clock = 17
  assert.equal(await cache.get('price:old', value => value), undefined)
  assert.ok(store.deletes.includes('price:old'))
  await cache.put('price:corrupt', { value: 2 })
  store.rows.set('price:corrupt', { ...(store.rows.get('price:corrupt') as DetailPriceEntry), value: { value: 999 } })
  assert.equal(await cache.get('price:corrupt', value => value), undefined)
  await cache.put('price:invalid', { value: 3 })
  assert.equal(await cache.get('price:invalid', () => { throw Error('identity mismatch') }), undefined)
  assert.ok(store.deletes.includes('price:invalid'))
})

test('unavailable or corrupt storage is fail-soft and does not invent cached prices', async () => {
  const unavailable = createDetailPriceDiskCache({
    transact: async () => { throw Error('offline') },
  })
  assert.equal(await unavailable.get('price:x', String), undefined)
  await unavailable.put('price:x', 'x')
  assert.equal(unavailable.stats().persistent, false)

  const broken = storage()
  broken.rows.set('__meta__', { key: '__meta__', version: 1, entries: [{ key: 'price:x', savedAt: 1, usedAt: 1, bytes: -1 }] })
  const cache = createDetailPriceDiskCache(broken.adapter)
  assert.equal(await cache.get('price:x', String), undefined)
  assert.equal(cache.stats().persistent, false)
})

test('a timed-out storage callback cannot mutate or refresh a stale value later', async () => {
  let resume: () => void = () => {}
  const delayed = new Promise<void>(resolve => { resume = resolve })
  let mutations = 0
  const cache = createDetailPriceDiskCache({
    async transact(_key, change) {
      await delayed
      const result = change(undefined, undefined)
      mutations++
      return result.result
    },
  }, { timeoutMs: 5 })
  await cache.put('price:old', 'old response')
  assert.equal(cache.stats().persistent, false)
  resume()
  await new Promise(resolve => setTimeout(resolve, 5))
  assert.equal(mutations, 0)
})
