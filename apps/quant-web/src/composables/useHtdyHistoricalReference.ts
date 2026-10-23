import { computed, ref } from 'vue'
import type { HtdyHistoricalResponse } from '../types/htdyReference'
export function isHtdyReferenceStale(computedThrough: string | undefined, latestBar: string | null): boolean {
  return Boolean(computedThrough && latestBar && Date.parse(latestBar) > Date.parse(computedThrough))
}
export function validHtdyWindow(since: string, through: string): boolean {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(since) || !/^\d{4}-\d{2}-\d{2}$/.test(through)) return false
  const start = Date.parse(since), end = Date.parse(through)
  return Number.isFinite(start) && Number.isFinite(end) && new Date(start).toISOString().slice(0, 10) === since && new Date(end).toISOString().slice(0, 10) === through && end >= start && end - start <= 365 * 86400000
}
export function useHtdyHistoricalReference(fetchPage: (symbol: string, params: { frequency: string; before?: string; since?: string; through?: string; as_of?: string; limit: number }, signal: AbortSignal) => Promise<HtdyHistoricalResponse>) {
  const result = ref<HtdyHistoricalResponse | null>(null)
  const latestBar = ref<string | null>(null)
  const stale = computed(() => isHtdyReferenceStale(result.value?.computed_through, latestBar.value))
  const loading = ref(false)
  const error = ref<string | null>(null)
  let controller = new AbortController()
  let generation = 0
  let identity: { symbol: string; frequency: string } | null = null
  async function read(more = false, window?: { since: string; through: string }) {
    if (!identity || loading.value) return
    if (window && !validHtdyWindow(window.since, window.through)) { error.value = '日期窗口须有效且不超过365天'; return }
    const current = generation
    const cursor = more ? result.value?.next_cursor : undefined
    if (more && !cursor) return
    loading.value = true; error.value = null
    try {
      const next = await fetchPage(identity.symbol, { frequency: identity.frequency, before: cursor || undefined, ...(more && result.value ? { since: result.value.since, through: result.value.through, as_of: result.value.computed_through } : window ?? (result.value ? { since: result.value.since, through: result.value.through } : {})), limit: 50 }, controller.signal)
      if (generation !== current) return
      if (next.schema_version !== 'htdy_historical_reference_v1' || next.recording_mode !== 'historical_replay' || next.product.toLowerCase() !== identity?.symbol.toLowerCase() || next.frequency !== identity?.frequency || !Array.isArray(next.trades) || !Array.isArray(next.signals)) throw new Error('identity')
      if (more && (result.value?.source_token !== next.source_token || result.value?.since !== next.since || result.value?.through !== next.through || result.value?.computed_through !== next.computed_through || next.next_cursor === cursor)) throw new Error('source')
      result.value = more && result.value ? { ...next, trades: [...new Map([...result.value.trades, ...next.trades].map(trade => [trade.reference_trade_id, trade])).values()] } : next
    } catch {
      if (generation === current) error.value = '历史参考读取失败或来源已变化，请重新读取'
    } finally { if (generation === current) loading.value = false }
  }
  function reset(symbol: string, frequency: string) {
    controller.abort(); controller = new AbortController(); generation += 1
    latestBar.value = null
    identity = { symbol, frequency }; result.value = null; loading.value = false; error.value = null
  }
  function dispose() { controller.abort(); generation += 1 }
  return { result, loading, error, stale, latestBar, read, reset, dispose }
}
