import { homeSnapshotCache } from './homeSnapshotCache.ts'
import { getMarketProductDirectory, normalizeMarketProductDirectory } from './market.ts'
import type { MarketProductDirectoryResponse } from '../types/market.ts'

const DIRECTORY_TTL_MS = 24 * 60 * 60_000
let pending: Promise<MarketProductDirectoryResponse> | null = null

/** Share the home directory's validated 24-hour display snapshot with detail selectors. */
export async function loadMarketProductDirectory(): Promise<MarketProductDirectoryResponse> {
  if (pending) return pending
  pending = (async () => {
    await homeSnapshotCache.restore()
    const snapshot = homeSnapshotCache.peek('product-directory')
    if (snapshot && snapshot.savedAt <= Date.now() && Date.now() - snapshot.savedAt < DIRECTORY_TTL_MS) {
      try { return normalizeMarketProductDirectory(snapshot.value) } catch { await homeSnapshotCache.discard('product-directory') }
    }
    const directory = await getMarketProductDirectory()
    await homeSnapshotCache.put('product-directory', directory)
    return directory
  })().finally(() => { pending = null })
  return pending
}
