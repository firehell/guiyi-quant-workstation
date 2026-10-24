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
  let active: HtdyHistoricalResponse | null = null
  let pageCount = 0
  let identity: { symbol: string; frequency: string } | null = null
  async function read(more = false, window?: { since: string; through: string }) {
    if (!identity || loading.value) return
    if (window && !validHtdyWindow(window.since, window.through)) { error.value = '日期窗口须有效且不超过365天'; return }
    const current = generation
    const cursor = more ? active?.next_cursor : undefined
    const earlier = more && !cursor ? active?.previous_window : null
    if (more && (!cursor && !earlier || pageCount >= 100 || result.value?.history_capped)) return
    loading.value = true; error.value = null
    try {
      const next = await fetchPage(identity.symbol, { frequency: identity.frequency, before: cursor || undefined, ...(more && active ? (cursor ? { since: active.since, through: active.through, as_of: active.computed_through } : earlier!) : window ?? (result.value ? { since: result.value.since, through: result.value.through } : {})), limit: 50 }, controller.signal)
      if (generation !== current) return
      if (next.schema_version !== 'htdy_historical_reference_v1' || next.recording_mode !== 'historical_replay' || next.product.toLowerCase() !== identity?.symbol.toLowerCase() || next.frequency !== identity?.frequency || !Array.isArray(next.trades) || !Array.isArray(next.signals)) throw new Error('identity')
      if (next.previous_window && (!validHtdyWindow(next.previous_window.since, next.previous_window.through) || next.previous_window.through >= next.since)) throw new Error('window')
      if (more && cursor && (active?.source_token !== next.source_token || active?.since !== next.since || active?.through !== next.through || active?.computed_through !== next.computed_through || next.next_cursor === cursor)) throw new Error('source')
      if (earlier && (next.since !== earlier.since || next.through !== earlier.through || next.through >= active!.since)) throw new Error('window')
      const combined = more && result.value ? [...result.value.trades, ...next.trades.filter(trade => !result.value!.trades.some(prior => prior.reference_trade_id === trade.reference_trade_id))] : next.trades
      if (combined.length > 10000) { if (result.value) result.value.history_capped = true; throw new Error('capacity') }
      pageCount = more ? pageCount + 1 : 1
      active = next
      const sources = more ? result.value?.history_sources ?? [] : []
      const source = { since: next.since, through: next.through, source: next.source_token }
      const history_sources = sources.some(item => item.since === source.since && item.through === source.through && item.source === source.source) ? sources : [...sources, source]
      result.value = { ...(more && result.value ? result.value : next), trades: combined, next_cursor: next.next_cursor, previous_window: next.previous_window, loaded_history_since: next.since, history_sources, history_capped: pageCount >= 100 || combined.length >= 10000 }

    } catch {
      if (generation === current) error.value = '历史参考读取失败或来源已变化，请重新读取'
    } finally { if (generation === current) loading.value = false }
  }
  function reset(symbol: string, frequency: string) {
    controller.abort(); controller = new AbortController(); generation += 1
    active = null; pageCount = 0
    latestBar.value = null
    identity = { symbol, frequency }; result.value = null; loading.value = false; error.value = null
  }
  function dispose() { controller.abort(); generation += 1 }
  return { result, loading, error, stale, latestBar, read, reset, dispose }
}
