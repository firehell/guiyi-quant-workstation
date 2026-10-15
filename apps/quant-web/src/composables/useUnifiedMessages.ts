import { ref, shallowRef } from 'vue'
import { getMarketMessages, messageQueryIdentity, type UnifiedMessagePage, type UnifiedMessageQuery } from '../api/marketMessages.ts'

type Fetcher = typeof getMarketMessages
const cache = new Map<string, { page: UnifiedMessagePage; at: number }>()
export function useUnifiedMessages(fetcher: Fetcher = getMarketMessages, cacheKey = '') {
  const page = shallowRef<UnifiedMessagePage | null>(null)
  const loading = ref(false)
  const loadingMore = ref(false)
  const error = ref<'stale' | 'failed' | null>(null)
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
    if (key !== queryKey) page.value = null
    query = { ...next }; queryKey = key
    const cached = cacheKey ? cache.get(`${cacheKey}:${key}`) : null
    if (cached) page.value = cached.page
    loading.value = false; loadingMore.value = false; error.value = null
    if (cached && !force && Date.now() - cached.at < 300_000) return
    loading.value = true
    try {
      const result = await fetcher(next, request.signal)
      if (current === generation) { page.value = result; remember() }
    } catch (reason) { if (current === generation && !request.signal.aborted) error.value = isStale(reason) ? 'stale' : 'failed' }
    finally { if (current === generation) loading.value = false }
  }
  async function loadMore() {
    if (!query || !page.value?.next_cursor || loading.value || loadingMore.value || error.value === 'stale') return
    const current = generation
    const request = controller!
    loadingMore.value = true; error.value = null
    try {
      const next = await fetcher(query, request.signal, page.value.next_cursor)
      if (current !== generation) return
      const known = new Set(page.value!.items.map(row => `${row.source}:${row.id}`))
      page.value = { ...next, items: [...page.value!.items, ...next.items.filter(row => !known.has(`${row.source}:${row.id}`))] }; remember()
    } catch (reason) { if (current === generation && !request.signal.aborted) error.value = isStale(reason) ? 'stale' : 'failed' }
    finally { if (current === generation) loadingMore.value = false }
  }
  function remember() {
    if (!cacheKey || !page.value) return
    const key = `${cacheKey}:${queryKey}`
    cache.delete(key); cache.set(key, { page: page.value, at: Date.now() })
    while (cache.size > 8) cache.delete(cache.keys().next().value!)
  }
  function dispose() { generation++; controller?.abort(); loading.value = false; loadingMore.value = false }
  return { page, loading, loadingMore, error, load, loadMore, dispose }
}
function isStale(value: unknown) { return (value as { response?: { status?: number } })?.response?.status === 409 }
