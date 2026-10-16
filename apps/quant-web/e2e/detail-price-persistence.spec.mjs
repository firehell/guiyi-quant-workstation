import { expect, test } from '@playwright/test'

test('two tabs share the latest price LRU index in one IndexedDB transaction', async ({ context, page }) => {
  const name = `detail-price-concurrency-${crypto.randomUUID()}`
  const second = await context.newPage()
  await Promise.all([page.goto('/market'), second.goto('/market')])
  const initialize = async (tab, clock) => tab.evaluate(async ({ name, clock }) => {
    const { createDetailPriceDiskCache, indexedDetailPriceStorage } = await import('/src/utils/detailPricePersistence.ts')
    globalThis.priceClock = clock
    globalThis.priceCache = createDetailPriceDiskCache(indexedDetailPriceStorage(name), {
      now: () => globalThis.priceClock, maxBytes: 400, timeoutMs: 1000,
    })
  }, { name, clock })
  await initialize(page, 1)
  await initialize(second, 2)
  await page.evaluate(() => globalThis.priceCache.put('price:a', 'a'.repeat(30)))
  await second.evaluate(() => globalThis.priceCache.put('price:b', 'b'.repeat(30)))
  await page.evaluate(() => { globalThis.priceClock = 3 })
  expect(await page.evaluate(() => globalThis.priceCache.get('price:a', String))).toBe('a'.repeat(30))
  await second.evaluate(() => { globalThis.priceClock = 4 })
  await second.evaluate(() => globalThis.priceCache.put('price:c', 'c'.repeat(30)))
  expect(await page.evaluate(() => globalThis.priceCache.get('price:b', String))).toBeUndefined()
  expect(await second.evaluate(() => globalThis.priceCache.get('price:a', String))).toBe('a'.repeat(30))
  const rows = await page.evaluate(async name => {
    const database = await new Promise((resolve, reject) => {
      const request = indexedDB.open(name, 2)
      request.onsuccess = () => resolve(request.result)
      request.onerror = () => reject(request.error)
    })
    try {
      return await new Promise((resolve, reject) => {
        const transaction = database.transaction('snapshots', 'readonly')
        const store = transaction.objectStore('snapshots')
        const keys = store.getAllKeys(), meta = store.get('__meta__')
        transaction.oncomplete = () => resolve({ keys: keys.result, index: meta.result })
        transaction.onerror = () => reject(transaction.error)
      })
    } finally { database.close() }
  }, name)
  expect(rows.keys.filter(key => key !== '__meta__').sort()).toEqual(rows.index.entries.map(item => item.key).sort())
  expect(rows.keys).not.toContain('price:b')
})
