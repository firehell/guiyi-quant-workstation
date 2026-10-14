import { createHomeSnapshotCache, indexedHomeStorage } from '../utils/marketHomePersistence.ts'
import { normalizeApiBaseURL } from '../utils/network.ts'
import { candidatePreview } from '../utils/candidatePreview.ts'
// Origin, API endpoint, preview mode, schema and formula contract isolate display data.
export const homeCacheNamespace = JSON.stringify([globalThis.location?.origin ?? 'server', normalizeApiBaseURL(import.meta.env?.VITE_API_BASE_URL?.trim()), candidatePreview.enabled, import.meta.env?.VITE_APP_VERSION ?? 'development', 'market-home-v1', 'newow_home_cards_v2', 'newow_home_display_v1'])
export const homeSnapshotCache = createHomeSnapshotCache(indexedHomeStorage(`guiyi-home:${homeCacheNamespace}`))
