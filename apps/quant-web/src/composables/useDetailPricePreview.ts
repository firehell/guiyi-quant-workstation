import { computed, onBeforeUnmount, shallowRef, watch, type Ref } from 'vue'
import { getMarketBarsPage } from '../api/market.ts'
import { peekDetailPrice, rememberDetailPrice, restoreDetailPrice } from '../api/detailPriceCache.ts'
import { validateDetailPrice } from '../utils/detailPricePreview.ts'
import type { MarketDetailIdentity } from '../types/marketDetail.ts'
import type { BarData, MarketBarsPageRequest, MarketBarsPageResponse } from '../types/market.ts'

export function useDetailPricePreview(identity: Readonly<Ref<MarketDetailIdentity | null>>) {
  const page = shallowRef<MarketBarsPageResponse | null>(null)
  const error = shallowRef<string | null>(null)
  const loading = shallowRef(false)
  const cached = shallowRef(false)
  let controller: AbortController | null = null
  function refresh() {
    controller?.abort()
    const owner = controller = new AbortController()
    const current = identity.value
    if (!current) { page.value = null; loading.value = false; error.value = null; return }
    const query: MarketBarsPageRequest = { symbol: current.symbol, series_kind: current.seriesKind, frequency: current.frequency, ...(current.contract ? { contract: current.contract } : {}), limit: 500 }
    page.value = peekDetailPrice(query) ?? null
    cached.value = page.value !== null
    error.value = null
    loading.value = true
    let fresh = false
    void restoreDetailPrice(query).then(value => {
      if (!owner.signal.aborted && !fresh && value && !page.value) { page.value = value; cached.value = true }
    })
    void getMarketBarsPage(query, owner.signal).then(value => {
      if (owner.signal.aborted) return
      value = validateDetailPrice(value, query)
      fresh = true; page.value = value; cached.value = false
      rememberDetailPrice(query, value)
    }).catch(() => {
      if (!owner.signal.aborted) error.value = '价格读取失败；已有价格仅作历史预览'
    }).finally(() => { if (!owner.signal.aborted) loading.value = false })
  }
  watch(() => [identity.value?.symbol, identity.value?.frequency, identity.value?.seriesKind, identity.value?.contract].join('|'), refresh, { immediate: true, flush: 'sync' })
  onBeforeUnmount(() => controller?.abort())
  const bars = computed<BarData[]>(() => page.value?.bars.map(bar => {
    const segment = page.value!.resolved_contract_segments.find(item => item.start_trading_day <= bar.trading_day && item.end_trading_day >= bar.trading_day)
    return { time: bar.bar_end, trading_day: bar.trading_day, physicalContract: segment?.contract, calculationSegmentId: segment ? `${segment.contract}:${segment.start_trading_day}` : undefined, open: bar.open, high: bar.high, low: bar.low, close: bar.close, volume: bar.volume }
  }) ?? [])
  return { bars, cached, loading, error, refresh, cutoff: computed(() => page.value?.bars.at(-1)?.bar_end ?? null) }
}

export type DetailPricePreview = ReturnType<typeof useDetailPricePreview>
