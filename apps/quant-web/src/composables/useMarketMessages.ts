import { shallowRef } from 'vue'
import type { AlertEvent, AlertHistoryResponse, AlertRuleCode } from '../types/market.ts'
import { alertEventIdentityKey } from '../utils/alertRules.ts'

export interface MarketMessageQuery { startDay: string; endDay: string; symbol: string; ruleCode: AlertRuleCode | null }
type FetchHistory = (query: MarketMessageQuery & { before?: string | null; limit?: number }, signal: AbortSignal) => Promise<AlertHistoryResponse>

export function useMarketMessages(options: { fetchHistory?: FetchHistory } = {}) {
  const items = shallowRef<AlertEvent[]>([])
  const nextBefore = shallowRef<string | null>(null)
  const loading = shallowRef(false)
  const loadingMore = shallowRef(false)
  const error = shallowRef<'request-failed' | null>(null)
  const fetchHistory = options.fetchHistory ?? (async (query, signal) => (await import('../api/alerts.ts')).getAlertHistory(query, signal))
  let generation = 0
  let controller: AbortController | null = null
  let currentQuery: MarketMessageQuery | null = null
  let morePromise: Promise<void> | null = null

  async function load(query: MarketMessageQuery): Promise<void> {
    const current = ++generation
    controller?.abort()
    controller = new AbortController()
    currentQuery = { ...query }
    items.value = []
    nextBefore.value = null
    error.value = null
    loading.value = true
    try {
      const page = await fetchHistory(query, controller.signal)
      if (current !== generation) return
      items.value = page.items
      nextBefore.value = page.next_before
    } catch {
      if (current === generation && !controller.signal.aborted) error.value = 'request-failed'
    } finally {
      if (current === generation) loading.value = false
    }
  }

  function loadMore(): Promise<void> {
    if (morePromise) return morePromise
    if (!currentQuery || !nextBefore.value) return Promise.resolve()
    const current = generation
    const before = nextBefore.value
    const signal = controller?.signal ?? new AbortController().signal
    loadingMore.value = true
    const request = fetchHistory({ ...currentQuery, before }, signal).then((page) => {
      if (current !== generation) return
      const known = new Set(items.value.map(alertEventIdentityKey))
      items.value = [...items.value, ...page.items.filter((item) => !known.has(alertEventIdentityKey(item)))]
      nextBefore.value = page.next_before
    }).catch(() => {
      if (current === generation && !signal.aborted) error.value = 'request-failed'
    }).finally(() => {
      if (current === generation) loadingMore.value = false
      if (morePromise === request) morePromise = null
    })
    morePromise = request
    return request
  }

  function dispose() { generation += 1; controller?.abort(); morePromise = null; loading.value = false; loadingMore.value = false }
  return { items, nextBefore, loading, loadingMore, error, load, loadMore, dispose }
}
