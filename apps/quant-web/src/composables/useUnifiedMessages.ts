import { ref, shallowRef } from 'vue'
import { getMarketMessages, messageQueryIdentity, type UnifiedMessagePage, type UnifiedMessageQuery } from '../api/marketMessages.ts'

type Fetcher = typeof getMarketMessages
const MAX_ITEMS = 300, MAX_BYTES = 2 * 1024 * 1024
const encodedSize = (value: unknown) => new TextEncoder().encode(JSON.stringify(value)).byteLength
const cache = new Map<string, { page: UnifiedMessagePage; at: number; bytes: number; capped: boolean }>()
export const unifiedMessageCacheStats = () => ({ entries: cache.size,
  bytes: [...cache.values()].reduce((sum, item) => sum + item.bytes, 0), maxBytes: MAX_BYTES })
export function useUnifiedMessages(fetcher: Fetcher = getMarketMessages, cacheKey = '') {
  const page = shallowRef<UnifiedMessagePage | null>(null)
  const loading = ref(false)
  const loadingMore = ref(false)
  const error = ref<'stale' | 'failed' | null>(null)
  const retentionCapped = ref(false)
  let generation = 0
  let controller: AbortController | null = null
  let query: UnifiedMessageQuery | null = null
  let queryKey = ''
  async function load(next: UnifiedMessageQuery, force = false) {
    // Stored preferences and newly-created filters may have different property order.
    // Cache identity follows filter values rather than object serialization order.
    const key = messageQueryIdentity(next)
    const current = ++generation
    controller?.abort(); controller = new AbortController()
    const request = controller
    if (key !== queryKey) { page.value = null; retentionCapped.value = false }
    query = { ...next }; queryKey = key
    const cached = cacheKey ? cache.get(`${cacheKey}:${key}`) : null
    if (cached) { page.value = cached.page; retentionCapped.value = cached.capped }
    loading.value = false; loadingMore.value = false; error.value = null
    if (cached && !force && Date.now() - cached.at < 300_000) return
    loading.value = true
    try {
      const result = await fetcher(next, request.signal)
      if (current === generation) { accept(result); remember() }
    } catch (reason) { if (current === generation && !request.signal.aborted) error.value = isStale(reason) ? 'stale' : 'failed' }
    finally { if (current === generation) loading.value = false }
  }
  async function loadMore() {
    if (!query || !page.value?.next_cursor || loading.value || loadingMore.value || error.value === 'stale' || retentionCapped.value) return
    const current = generation
    const request = controller!
    loadingMore.value = true; error.value = null
    try {
      const next = await fetcher(query, request.signal, page.value.next_cursor)
      if (current !== generation) return
      const known = new Set(page.value!.items.map(row => `${row.source}:${row.id}`))
      accept({ ...next, items: [...page.value!.items, ...next.items.filter(row => !known.has(`${row.source}:${row.id}`))] }); remember()
    } catch (reason) { if (current === generation && !request.signal.aborted) error.value = isStale(reason) ? 'stale' : 'failed' }
    finally { if (current === generation) loadingMore.value = false }
  }
  function accept(next: UnifiedMessagePage) {
    let bytes = encodedSize({ ...next, items: [] })
    const items: UnifiedMessagePage['items'][number][] = []
    for (const row of next.items) {
      const size = encodedSize(row) + (items.length ? 1 : 0)
      if (items.length >= MAX_ITEMS || bytes + size > MAX_BYTES) break
      items.push(row); bytes += size
    }
    retentionCapped.value = items.length < next.items.length || items.length >= MAX_ITEMS && next.next_cursor !== null
    page.value = { ...next, items }
  }
  function remember() {
    if (!cacheKey || !page.value) return
    const key = `${cacheKey}:${queryKey}`
    cache.delete(key); cache.set(key, { page: page.value, at: Date.now(), bytes: encodedSize(page.value), capped: retentionCapped.value })
    while (cache.size > 8 || [...cache.values()].reduce((sum, item) => sum + item.bytes, 0) > MAX_BYTES) cache.delete(cache.keys().next().value!)
  }
  function dispose() { generation++; controller?.abort(); loading.value = false; loadingMore.value = false }
  return { page, loading, loadingMore, error, retentionCapped, load, loadMore, dispose }
}
function isStale(value: unknown) { return (value as { response?: { status?: number } })?.response?.status === 409 }
