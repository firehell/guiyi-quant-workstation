import { createSessionResources } from '../utils/newowSessionResources.ts'
import { createDetailPriceDiskCache, indexedDetailPriceStorage } from '../utils/detailPricePersistence.ts'
import { validateDetailPrice } from '../utils/detailPricePreview.ts'
import { homeCacheNamespace } from './homeSnapshotCache.ts'
import type { MarketBarsPageRequest, MarketBarsPageResponse } from '../types/market.ts'

// Disposable prices only: neither this key nor its TTL authorizes strategy facts.
const memory = createSessionResources({ maxBytes: 8 * 1024 * 1024, ttl: 7 * 86400_000 })
const disk = createDetailPriceDiskCache(indexedDetailPriceStorage(`guiyi-detail-prices-v1:${homeCacheNamespace}`))
export const detailPriceCacheStats = () => memory.stats()
export const detailPriceKey = (query: MarketBarsPageRequest) => `price:${JSON.stringify([homeCacheNamespace, query.symbol, query.series_kind, query.contract ?? null, query.frequency, query.before ?? null, query.limit ?? 500])}`
export function peekDetailPrice(query: MarketBarsPageRequest): MarketBarsPageResponse | undefined {
  return memory.peek(detailPriceKey(query))
}
let diskWork = Promise.resolve()
function withDisk<T>(operation: () => Promise<T>): Promise<T> {
  const result = diskWork.then(operation)
  diskWork = result.then(() => undefined, () => undefined)
  return result
}
export async function restoreDetailPrice(query: MarketBarsPageRequest): Promise<MarketBarsPageResponse | undefined> {
  return withDisk(() => disk.get(detailPriceKey(query), value => validateDetailPrice(value, query)))
}
export function rememberDetailPrice(query: MarketBarsPageRequest, page: MarketBarsPageResponse) {
  const key = detailPriceKey(query)
  memory.put(key, page, JSON.stringify([page.canonical_coverage, page.resolved_contract_segments]))
  void withDisk(() => disk.put(key, page)).catch(() => undefined)
}
