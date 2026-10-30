import { computed, getCurrentScope, onScopeDispose, readonly, shallowRef, watch, type Ref } from 'vue'
import type { MarketBarsPageRequest, MarketBarsPageResponse, MarketHomeLiveItem } from '../types/market.ts'
import type { MarketDetailHeaderModel, MarketDetailIdentity } from '../types/marketDetail.ts'
import { formatChartTimeInShanghai } from '../utils/barTime.ts'
import { useMarketHomeLive } from './useMarketHomeLive.ts'

export interface MarketDetailDailyFacts {
  open: number; high: number; low: number; close: number; volume: number
  turnover: number | null; openInterest: number | null
  asOf: string; tradingDay: string; physicalContract: string
  change: number | null; pct: number | null
}
export interface MarketDetailQuote {
  close: number; change: number | null; pct: number | null; previousClose: number | null
  asOf: string; tradingDay: string; physicalContract: string
  source: 'completed_1m' | 'completed_1d'
  freshness: MarketDetailHeaderModel['freshness']; phase: string
  daily: MarketDetailDailyFacts | null
  /** Each source keeps its own date; D1 never claims to be today's intraday OHLCV. */
  title: string
}
interface Options {
  identity: Readonly<Ref<MarketDetailIdentity | null>>
  /** Disable current quotes for frozen candidate/snapshot workspaces. */
  enabled?: Readonly<Ref<boolean>>
  snapshotBefore?: Readonly<Ref<string | null>>
  live?: ReturnType<typeof useMarketHomeLive>
  fetchPage?: (request: MarketBarsPageRequest, signal: AbortSignal) => Promise<MarketBarsPageResponse>
}

function dailyFacts(page: MarketBarsPageResponse, request: MarketBarsPageRequest): MarketDetailDailyFacts | null {
  const invalid = () => { throw new Error('DETAIL_DAILY_QUOTE_INVALID') }
  const echo = page.request
  if (echo.symbol !== request.symbol || echo.series_kind !== request.series_kind || echo.frequency !== '1d'
    || echo.limit !== 2 || echo.contract !== (request.contract ?? null) || echo.before !== (request.before ?? null)) invalid()
  if (!page.bars.length) return null
  if (page.bars.length > 2 || !page.canonical_coverage) invalid()
  const coveredDay = (value: string) => value.includes('T') ? formatChartTimeInShanghai(value).slice(0, 10) : value
  const coverage = page.canonical_coverage!
  if (![coverage.start, coverage.end].every(value => Number.isFinite(Date.parse(value))) || Date.parse(coverage.start) > Date.parse(coverage.end)) invalid()
  let previousTime = -Infinity, previousDay = ''
  const owners = page.bars.map(bar => {
    const time = Date.parse(bar.bar_end)
    if (!/^\d{4}-\d{2}-\d{2}T.*(?:Z|[+-]\d{2}:\d{2})$/.test(bar.bar_end) || !Number.isFinite(time) || time <= previousTime
      || !/^\d{4}-\d{2}-\d{2}$/.test(bar.trading_day) || bar.trading_day <= previousDay
      || formatChartTimeInShanghai(bar.bar_end).slice(0, 10) !== bar.trading_day
      || bar.trading_day < coveredDay(coverage.start) || bar.trading_day > coveredDay(coverage.end)
      || (coverage.start.includes('T') && time < Date.parse(coverage.start)) || (coverage.end.includes('T') && time > Date.parse(coverage.end))
      || (request.before && time >= Date.parse(request.before))) invalid()
    if (![bar.open, bar.high, bar.low, bar.close, bar.volume].every(Number.isFinite) || bar.low <= 0
      || bar.high < Math.max(bar.open, bar.close, bar.low) || bar.low > Math.min(bar.open, bar.close) || bar.volume < 0
      || [bar.turnover, bar.open_interest].some(value => value !== null && (!Number.isFinite(value) || value < 0))) invalid()
    previousTime = time; previousDay = bar.trading_day
    const matches = page.resolved_contract_segments.filter(segment => segment.start_trading_day <= bar.trading_day && bar.trading_day <= segment.end_trading_day)
    if (request.series_kind === 'contract') return request.contract!.toUpperCase()
    if (matches.length !== 1 || !/^[A-Z]+\d+$/i.test(matches[0]!.contract)
      || matches[0]!.contract.replace(/\d+$/, '').toLowerCase() !== request.symbol) invalid()
    return matches[0]!.contract.toUpperCase()
  })
  const latest = page.bars.at(-1)!, previous = page.bars.at(-2)
  const change = previous && owners[0] === owners[1] ? latest.close - previous.close : null
  return { open:latest.open, high:latest.high, low:latest.low, close:latest.close, volume:latest.volume,
    turnover:latest.turnover, openInterest:latest.open_interest, asOf:latest.bar_end, tradingDay:latest.trading_day,
    physicalContract:owners.at(-1)!, change, pct:change === null || !previous ? null : change / previous.close * 100 }
}

/** One session per detail page; chart period and strategy never restart its sources. */
export function useMarketDetailQuote(options: Options) {
  const live = options.live ?? useMarketHomeLive()
  const daily = shallowRef<MarketDetailDailyFacts | null>(null)
  const state = shallowRef<'loading' | 'ready' | 'unavailable'>('unavailable')
  const fetchPage = options.fetchPage ?? (async (request, signal) => (await import('../api/market.ts')).getMarketBarsPage(request, signal))
  const enabled = computed(() => options.enabled?.value !== false)
  const before = computed(() => options.snapshotBefore?.value ?? options.identity.value?.focusBarEnd ?? null)
  const item = computed<MarketHomeLiveItem | null>(() => {
    const identity = options.identity.value
    if (!enabled.value || !identity || before.value) return null
    const value = live.items.value.get(identity.symbol)
    if (!value || value.source === 'none' || value.availability === 'unavailable' || !value.physicalContract || !value.tradingDay || !value.barEnd || value.price === null) return null
    if (value.symbol !== identity.symbol || !/^[A-Z]+\d+$/i.test(value.physicalContract)
      || value.physicalContract.replace(/\d+$/, '').toLowerCase() !== identity.symbol) return null
    if (identity.seriesKind === 'contract' && value.physicalContract.toUpperCase() !== identity.contract?.toUpperCase()) return null
    return value
  })
  let generation = 0, controller: AbortController | null = null, disposed = false
  function refresh() {
    const current = ++generation
    controller?.abort(); daily.value = null
    const identity = options.identity.value
    if (!enabled.value || !identity) { state.value = 'unavailable'; return }
    const request: MarketBarsPageRequest = { symbol:identity.symbol, series_kind:identity.seriesKind, frequency:'1d', limit:2,
      ...(identity.seriesKind === 'contract' ? {contract:identity.contract} : {}), ...(before.value ? {before:before.value} : {}) }
    if (before.value && !Number.isFinite(Date.parse(before.value))) { state.value = 'unavailable'; return }
    const signal = (controller = new AbortController()).signal
    state.value = 'loading'
    void fetchPage(request, signal).then(response => {
      if (disposed || signal.aborted || current !== generation) return
      const facts = dailyFacts(response, request)
      daily.value = facts; state.value = facts ? 'ready' : 'unavailable'
    }).catch(() => { if (!disposed && !signal.aborted && current === generation) { daily.value = null; state.value = 'unavailable' } })
  }
  const stop = watch(() => [enabled.value, options.identity.value?.symbol, options.identity.value?.seriesKind,
    options.identity.value?.contract, before.value, item.value?.physicalContract, item.value?.tradingDay].join('|'), refresh, {immediate:true,flush:'sync'})
  if (enabled.value) live.start()
  const stopEnabled = watch(enabled, value => { if (value) live.start() })
  const quote = computed<MarketDetailQuote | null>(() => {
    if (!enabled.value || !options.identity.value) return null
    const current = item.value
    const snapshot = daily.value
    const usable = current && (!snapshot || current.tradingDay! >= snapshot.tradingDay) ? current : null
    if (usable) {
      const sameOwnerDaily = snapshot?.physicalContract === usable.physicalContract ? snapshot : null
      const previousClose = usable.previousClose
      return { close:usable.price!,change:usable.priceChange,pct:usable.priceChange !== null && previousClose !== null && previousClose !== 0 ? usable.priceChange / previousClose * 100 : null,
        previousClose,asOf:usable.barEnd!,tradingDay:usable.tradingDay!,physicalContract:usable.physicalContract!,source:usable.source as 'completed_1m'|'completed_1d',
        freshness:usable.availability === 'live' && !live.stale.value && live.connection.value === 'connected' ? 'fresh' : 'stale',phase:usable.phase,daily:sameOwnerDaily,
        title:`最新价 ${usable.physicalContract} · 交易日 ${usable.tradingDay} · ${usable.barEnd}；日线 OHLCV ${sameOwnerDaily ? `${sameOwnerDaily.physicalContract} · 交易日 ${sameOwnerDaily.tradingDay} · ${sameOwnerDaily.asOf}` : '不可用'}` }
    }
    if (!snapshot) return null
    return {close:snapshot.close,change:snapshot.change,pct:snapshot.pct,previousClose:snapshot.change === null ? null : snapshot.close-snapshot.change,
      asOf:snapshot.asOf,tradingDay:snapshot.tradingDay,physicalContract:snapshot.physicalContract,source:'completed_1d',freshness:'stale',phase:'UNKNOWN',daily:snapshot,
      title:`历史日线快照 ${snapshot.physicalContract} · 交易日 ${snapshot.tradingDay} · ${snapshot.asOf}`}
  })
  function dispose() { disposed = true; ++generation; controller?.abort(); stop(); stopEnabled(); live.dispose(); daily.value = null }
  if (getCurrentScope()) onScopeDispose(dispose)
  return {quote,state:readonly(state),connection:live.connection,refresh,dispose}
}
export type MarketDetailQuoteSession = ReturnType<typeof useMarketDetailQuote>

/** Keep catalog identity/disclosures; all numeric fields use this quote's sources. */
export function projectMarketDetailQuoteHeader(base: MarketDetailHeaderModel, quote: MarketDetailQuote | null): MarketDetailHeaderModel {
  if (!quote) return {...base,frequency:'1d',displayContract:null,asOf:null,tradingDay:null,
    open:null,high:null,low:null,close:null,change:null,pct:null,volume:null,turnover:null,openInterest:null,
    phase:'UNKNOWN',freshness:'unavailable',afterMarketFailed:undefined,extendedSections:[],displaySource:'详情报价不可用'}
  return {...base,frequency:'1d',displayContract:quote.physicalContract,asOf:quote.asOf,tradingDay:quote.tradingDay,
    close:quote.close,change:quote.change,pct:quote.pct,open:quote.daily?.open ?? null,high:quote.daily?.high ?? null,low:quote.daily?.low ?? null,
    volume:quote.daily?.volume ?? null,turnover:quote.daily?.turnover ?? null,openInterest:quote.daily?.openInterest ?? null,
    freshness:quote.freshness,phase:quote.phase,afterMarketFailed:undefined,extendedSections:[],displaySource:quote.title}
}
