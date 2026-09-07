import { computed, readonly, shallowRef, watch, type Ref } from 'vue'
import type { MarketBarsPageRequest, MarketBarsPageResponse } from '../types/market.ts'
import { resolveHistoricalPhysicalContract } from './useMarketSeries.ts'

export function projectNewowDailyQuote(page: MarketBarsPageResponse, symbol: string, contract: string) {
  const invalid = () => { throw new Error('NEWOW_DAILY_QUOTE_INVALID') }
  const request = page.request
  if (request.series_kind !== 'actual_dominant' || request.symbol !== symbol || request.frequency !== '1d' || request.limit !== 2 || request.before !== null || request.contract !== null) invalid()
  if (!page.bars.length || page.bars.length > 2 || !page.canonical_coverage) invalid()
  const coverage = page.canonical_coverage!
  if (coverage.start > coverage.end || !Number.isFinite(Date.parse(coverage.start)) || !Number.isFinite(Date.parse(coverage.end))) invalid()
  if (!page.resolved_contract_segments.length || page.resolved_contract_segments.some(segment => !/^[A-Z]+\d+$/i.test(segment.contract) || !/^\d{4}-\d{2}-\d{2}$/.test(segment.start_trading_day) || !/^\d{4}-\d{2}-\d{2}$/.test(segment.end_trading_day) || segment.start_trading_day > segment.end_trading_day)) invalid()
  let previousTime = -Infinity
  let previousDay = ''
  const owners = page.bars.map(bar => {
    const time = Date.parse(bar.bar_end)
    if (!Number.isFinite(time) || time <= previousTime || !/^\d{4}-\d{2}-\d{2}$/.test(bar.trading_day) || bar.trading_day <= previousDay || bar.trading_day < coverage.start.slice(0, 10) || bar.trading_day > coverage.end.slice(0, 10)) invalid()
    if (![bar.open, bar.high, bar.low, bar.close, bar.volume].every(Number.isFinite) || bar.low <= 0 || bar.high < Math.max(bar.open, bar.close, bar.low) || bar.low > Math.min(bar.open, bar.close) || bar.volume < 0 || (bar.turnover !== null && (!Number.isFinite(bar.turnover) || bar.turnover < 0)) || (bar.open_interest !== null && (!Number.isFinite(bar.open_interest) || bar.open_interest < 0))) invalid()
    previousTime = time; previousDay = bar.trading_day
    return resolveHistoricalPhysicalContract(page, bar)
  })
  const latest = page.bars.at(-1)!
  if (owners.at(-1) !== contract.toUpperCase()) invalid()
  const prior = page.bars.at(-2)
  const change = prior && owners[0] === owners[1] ? latest.close - prior.close : null
  return { close: latest.close, open: latest.open, high: latest.high, low: latest.low, volume: latest.volume, openInterest: latest.open_interest, asOf: latest.bar_end, change, pct: change === null || !prior ? null : change / prior.close * 100 }
}

export function useNewowDailyQuote(options: {
  symbol: Readonly<Ref<string | null>>
  contract: Readonly<Ref<string | null>>
  fetchPage?: (request: MarketBarsPageRequest, signal: AbortSignal) => Promise<MarketBarsPageResponse>
}) {
  const page = shallowRef<MarketBarsPageResponse | null>(null)
  const state = shallowRef<'loading' | 'ready' | 'unavailable'>('unavailable')
  const fetchPage = options.fetchPage ?? (async (request, signal) => (await import('../api/market.ts')).getMarketBarsPage(request, signal))
  let generation = 0
  let controller: AbortController | null = null
  const stop = watch(options.symbol, async symbol => {
    const current = ++generation
    controller?.abort(); page.value = null
    if (!symbol) { state.value = 'unavailable'; return }
    controller = new AbortController(); state.value = 'loading'
    try {
      const response = await fetchPage({ series_kind: 'actual_dominant', symbol, frequency: '1d', limit: 2 }, controller.signal)
      if (generation !== current) return
      page.value = response; state.value = 'ready'
    } catch { if (generation === current) state.value = 'unavailable' }
  }, { immediate: true, flush: 'sync' })
  const quote = computed(() => {
    if (!page.value || !options.symbol.value || !options.contract.value) return null
    try { return projectNewowDailyQuote(page.value, options.symbol.value, options.contract.value) } catch { return null }
  })
  return { quote, state: readonly(state), dispose() { ++generation; controller?.abort(); stop(); page.value = null } }
}
