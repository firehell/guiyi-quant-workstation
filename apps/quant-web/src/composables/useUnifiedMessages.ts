import { ref, shallowRef } from 'vue'
import { getMarketMessages, messageQueryIdentity, type UnifiedMessagePage, type UnifiedMessageQuery } from '../api/marketMessages.ts'

type Fetcher = typeof getMarketMessages
const MAX_ITEMS = 300, MAX_BYTES = 2 * 1024 * 1024
const FRESH_MS = 30_000, RETAIN_MS = 300_000
const encodedSize = (value: unknown) => new TextEncoder().encode(JSON.stringify(value)).byteLength
type Pending = { page: UnifiedMessagePage; at: number; capped: boolean }
type Entry = { page: UnifiedMessagePage; at: number; bytes: number; capped: boolean; pending: Pending | null }
const cache = new Map<string, Entry>()
export const unifiedMessageCacheStats = () => ({ entries: cache.size,
  bytes: [...cache.values()].reduce((sum, item) => sum + item.bytes, 0), maxBytes: MAX_BYTES })
export function useUnifiedMessages(fetcher: Fetcher = getMarketMessages, cacheKey = '') {
  const page = shallowRef<UnifiedMessagePage | null>(null)
  const pendingUpdate = shallowRef<Pending | null>(null)
  const loading = ref(false)
  const loadingMore = ref(false)
  const error = ref<'stale' | 'failed' | null>(null)
  const retentionCapped = ref(false)
  let generation = 0
  let controller: AbortController | null = null
  let query: UnifiedMessageQuery | null = null
  let queryKey = ''
  let firstPageAt = 0
  async function load(next: UnifiedMessageQuery, force = false) {
    const key = messageQueryIdentity(next)
    const current = ++generation
    controller?.abort(); controller = new AbortController()
    const request = controller
    if (key !== queryKey) { page.value = null; retentionCapped.value = false }
    query = { ...next }; queryKey = key
    const entryKey = `${cacheKey}:${key}`
    const entry = cacheKey ? cache.get(entryKey) : null
    const cached = !force && entry && Date.now() - entry.at < RETAIN_MS ? entry : null
    pendingUpdate.value = null
    if (cached) {
      page.value = cached.page; retentionCapped.value = cached.capped
      firstPageAt = cached.at; pendingUpdate.value = cached.pending
      cache.delete(entryKey); cache.set(entryKey, cached)
    } else if (entry && !force) cache.delete(entryKey)
    loading.value = false; loadingMore.value = false; error.value = null
    if (cached && Date.now() - cached.at < FRESH_MS) return
    loading.value = true
    try {
      const result = await fetcher(next, request.signal, undefined, cached?.page.items.length)
      if (current !== generation) return
      const at = Date.now()
      // Matching the full-source digest proves all retained rows. Rebind their
      // continuation to the new server snapshot instead of retaining an expired cursor.
      if (cached?.page.dataset_hash && cached.page.dataset_hash === result.dataset_hash && 'resume_cursor' in result) {
        page.value = { ...result, items: cached.page.items, next_cursor: result.resume_cursor ?? null }
        retentionCapped.value = cached.capped; pendingUpdate.value = null
      } else if (cached) {
        pendingUpdate.value = { ...bounded(result), at }
      } else {
        accept(result); pendingUpdate.value = null
      }
      firstPageAt = at; remember()
    } catch (reason) { if (current === generation && !request.signal.aborted) error.value = isStale(reason) ? 'stale' : 'failed' }
    finally { if (current === generation) loading.value = false }
  }
  function applyUpdate() {
    const pending = pendingUpdate.value
    if (!pending) return
    generation++; controller?.abort(); controller = new AbortController()
    loading.value = false; loadingMore.value = false; error.value = null
    page.value = pending.page; retentionCapped.value = pending.capped; firstPageAt = pending.at; pendingUpdate.value = null; remember()
  }
  async function loadMore() {
    if (!query || !page.value?.next_cursor || loading.value || loadingMore.value || error.value === 'stale' || retentionCapped.value) return
    const current = generation
    const request = controller!
    loadingMore.value = true; error.value = null
    try {
      const next = await fetcher(query, request.signal, page.value.next_cursor)
      if (current !== generation) return
      if (next.dataset_hash !== page.value!.dataset_hash || next.snapshot.cutoff !== page.value!.snapshot.cutoff || next.snapshot.alert_max_id !== page.value!.snapshot.alert_max_id) throw { response: { status: 409 } }
      const known = new Set(page.value!.items.map(row => `${row.source}:${row.id}`))
      accept({ ...next, items: [...page.value!.items, ...next.items.filter(row => !known.has(`${row.source}:${row.id}`))] }); remember()
    } catch (reason) { if (current === generation && !request.signal.aborted) error.value = isStale(reason) ? 'stale' : 'failed' }
    finally { if (current === generation) loadingMore.value = false }
  }
  function accept(next: UnifiedMessagePage) {
    const result = bounded(next)
    page.value = result.page; retentionCapped.value = result.capped
  }
  function bounded(next: UnifiedMessagePage) {
    let bytes = encodedSize({ ...next, items: [] })
    const items: UnifiedMessagePage['items'][number][] = []
    for (const row of next.items) {
      const size = encodedSize(row) + (items.length ? 1 : 0)
      if (items.length >= MAX_ITEMS || bytes + size > MAX_BYTES) break
      items.push(row); bytes += size
    }
    return { page: { ...next, items }, capped: items.length < next.items.length || items.length >= MAX_ITEMS && next.next_cursor !== null }
  }
  function remember() {
    if (!cacheKey || !page.value) return
    const key = `${cacheKey}:${queryKey}`
    const bytes = encodedSize(page.value) + (pendingUpdate.value ? encodedSize(pendingUpdate.value.page) : 0)
    cache.delete(key)
    // A large pending result must not defeat the shared memory budget.
    if (bytes <= MAX_BYTES) cache.set(key, { page: page.value, at: firstPageAt, bytes, capped: retentionCapped.value, pending: pendingUpdate.value })
    while (cache.size > 8 || [...cache.values()].reduce((sum, item) => sum + item.bytes, 0) > MAX_BYTES) cache.delete(cache.keys().next().value!)
  }
  function dispose() { generation++; controller?.abort(); loading.value = false; loadingMore.value = false }
  return { page, pendingUpdate, loading, loadingMore, error, retentionCapped, load, loadMore, applyUpdate, dispose }
}
function isStale(value: unknown) { return (value as { response?: { status?: number } })?.response?.status === 409 }
