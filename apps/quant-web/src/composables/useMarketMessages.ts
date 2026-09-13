import { shallowRef } from 'vue'
import type { AlertEvent, AlertHistoryResponse, AlertRuleCode } from '../types/market.ts'
import { alertEventIdentityKey } from '../utils/alertRules.ts'

export interface MarketMessageQuery { startDay: string; endDay: string; symbol: string; ruleCode: AlertRuleCode | null }
type FetchHistory = (query: MarketMessageQuery & { before?: string | null; limit?: number }, signal: AbortSignal) => Promise<AlertHistoryResponse>
interface MarketMessagesOptions {
  fetchHistory?: FetchHistory
  cacheKey?: string
  cacheMaxAgeMs?: number
  now?: () => number
}
interface MessageCacheEntry {
  items: AlertEvent[]
  nextBefore: string | null
  updatedAt: number
  scrollTop: number
}
const MESSAGE_CACHE_MAX_ENTRIES = 8
const messageCache = new Map<string, MessageCacheEntry>()

export function useMarketMessages(options: MarketMessagesOptions = {}) {
  const items = shallowRef<AlertEvent[]>([])
  const nextBefore = shallowRef<string | null>(null)
  const loading = shallowRef(false)
  const loadingMore = shallowRef(false)
  const error = shallowRef<'request-failed' | null>(null)
  const fetchHistory = options.fetchHistory ?? (async (query, signal) => (await import('../api/alerts.ts')).getAlertHistory(query, signal))
  const now = options.now ?? Date.now
  const cacheMaxAgeMs = options.cacheMaxAgeMs ?? 5 * 60_000
  let generation = 0
  let controller: AbortController | null = null
  let currentQuery: MarketMessageQuery | null = null
  let morePromise: Promise<void> | null = null

  async function load(query: MarketMessageQuery, loadOptions: { force?: boolean } = {}): Promise<void> {
    const current = ++generation
    controller?.abort()
    controller = null
    morePromise = null
    loadingMore.value = false
    currentQuery = { ...query }
    const cached = readCache(query)
    items.value = cached?.items ?? []
    nextBefore.value = cached?.nextBefore ?? null
    error.value = null
    if (cached && !loadOptions.force && now() - cached.updatedAt <= cacheMaxAgeMs) {
      loading.value = false
      return
    }
    const requestController = new AbortController()
    controller = requestController
    loading.value = cached === null
    try {
      const page = await fetchHistory(query, requestController.signal)
      if (current !== generation) return
      items.value = page.items
      nextBefore.value = page.next_before
      writeCache(query, page.items, page.next_before)
    } catch {
      if (current === generation && !requestController.signal.aborted) error.value = 'request-failed'
    } finally {
      if (current === generation) loading.value = false
    }
  }

  function loadMore(): Promise<void> {
    if (morePromise) return morePromise
    if (!currentQuery || !nextBefore.value) return Promise.resolve()
    const current = generation
    const before = nextBefore.value
    const requestController = controller && !controller.signal.aborted ? controller : new AbortController()
    controller = requestController
    const signal = requestController.signal
    loadingMore.value = true
    const request = fetchHistory({ ...currentQuery, before }, signal).then((page) => {
      if (current !== generation) return
      const known = new Set(items.value.map(alertEventIdentityKey))
      items.value = [...items.value, ...page.items.filter((item) => !known.has(alertEventIdentityKey(item)))]
      nextBefore.value = page.next_before
      writeCache(currentQuery!, items.value, page.next_before)
    }).catch(() => {
      if (current === generation && !signal.aborted) error.value = 'request-failed'
    }).finally(() => {
      if (current === generation) loadingMore.value = false
      if (morePromise === request) morePromise = null
    })
    morePromise = request
    return request
  }

  function rememberScrollTop(scrollTop: number) {
    if (!currentQuery || !Number.isFinite(scrollTop) || scrollTop < 0) return
    const key = queryCacheKey(currentQuery)
    if (!key) return
    const cached = messageCache.get(key)
    if (!cached) return
    messageCache.delete(key)
    messageCache.set(key, { ...cached, scrollTop })
  }

  function restoreScrollTop(): number {
    if (!currentQuery) return 0
    return readCache(currentQuery)?.scrollTop ?? 0
  }

  function readCache(query: MarketMessageQuery): MessageCacheEntry | null {
    const key = queryCacheKey(query)
    if (!key) return null
    const cached = messageCache.get(key)
    if (!cached) return null
    messageCache.delete(key)
    messageCache.set(key, cached)
    return cached
  }

  function writeCache(query: MarketMessageQuery, accepted: AlertEvent[], before: string | null) {
    const key = queryCacheKey(query)
    if (!key) return
    const scrollTop = messageCache.get(key)?.scrollTop ?? 0
    messageCache.delete(key)
    messageCache.set(key, { items: [...accepted], nextBefore: before, updatedAt: now(), scrollTop })
    while (messageCache.size > MESSAGE_CACHE_MAX_ENTRIES) {
      const oldest = messageCache.keys().next().value
      if (oldest === undefined) break
      messageCache.delete(oldest)
    }
  }

  function queryCacheKey(query: MarketMessageQuery): string | null {
    if (!options.cacheKey) return null
    return `${options.cacheKey}:${JSON.stringify([query.startDay, query.endDay, query.symbol, query.ruleCode])}`
  }

  function dispose() { generation += 1; controller?.abort(); controller = null; morePromise = null; loading.value = false; loadingMore.value = false }
  return { items, nextBefore, loading, loadingMore, error, load, loadMore, rememberScrollTop, restoreScrollTop, dispose }
}
