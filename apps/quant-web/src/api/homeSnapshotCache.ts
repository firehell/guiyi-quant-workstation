import { createHomeSnapshotCache, indexedHomeStorage } from '../utils/marketHomePersistence.ts'
import { normalizeApiBaseURL } from '../utils/network.ts'
import { candidatePreview } from '../utils/candidatePreview.ts'
// Origin, API endpoint, preview mode, schema and formula contract isolate display data.
const directoryContract = import.meta.env?.VITE_GUIYI_MARKET_FOUNDATION === '1' ? 'market-foundation-directory-57' : 'market-home-v2-static-directory'
export const homeCacheNamespace = JSON.stringify([globalThis.location?.origin ?? 'server', normalizeApiBaseURL(import.meta.env?.VITE_API_BASE_URL?.trim()), candidatePreview.enabled, import.meta.env?.VITE_APP_VERSION ?? 'development', directoryContract, 'newow_home_projection_v1', 'newow_home_display_v1'])
export const homeSnapshotCache = createHomeSnapshotCache(indexedHomeStorage(`guiyi-home:${homeCacheNamespace}`), { acceptsKey: key => /^(overview|product-directory|card:[a-z0-9]+)$/.test(key) })
