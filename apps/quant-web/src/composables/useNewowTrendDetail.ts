import { computed, readonly, ref, watch, type Ref } from 'vue'

import {
  getNewowTrendDetail,
  NewowTrendDetailRequestError,
  type NewowTrendDetailRequest,
  type NewowTrendDetailRequestErrorCode,
} from '../api/newow.ts'
import type { BarData } from '../types/market.ts'
import type { MarketDetailIdentity } from '../types/marketDetail.ts'
import type { NewowTrendDetailResponse } from '../types/newow.ts'

export type NewowTrendDetailErrorCode =
  | 'NEWOW_WINDOW_INVALID'
  | 'NEWOW_DATA_IDENTITY_INVALID'
  | NewowTrendDetailRequestErrorCode

export interface UseNewowTrendDetailOptions {
  identity: Readonly<Ref<MarketDetailIdentity | null>>
  bars: Readonly<Ref<readonly BarData[]>>
  fetchDetail?: (
    params: NewowTrendDetailRequest,
    signal: AbortSignal,
  ) => Promise<NewowTrendDetailResponse>
}

interface NewowTrendWindow {
  from: string
  through: string
}

export function useNewowTrendDetail(options: UseNewowTrendDetailOptions) {
  const data = ref<NewowTrendDetailResponse | null>(null)
  const loading = ref(false)
  const error = ref<NewowTrendDetailErrorCode | null>(null)
  const fetchDetail = options.fetchDetail
    ?? ((params: NewowTrendDetailRequest, signal: AbortSignal) => getNewowTrendDetail(params, { signal }))
  let generation = 0
  let activeRequest: AbortController | null = null
  let disposed = false

  async function replace(): Promise<void> {
    const requestGeneration = ++generation
    activeRequest?.abort()
    activeRequest = null
    data.value = null
    loading.value = false
    error.value = null
    if (disposed) return

    const identity = options.identity.value
    if (!isNewowTrendIdentity(identity)) return
    const genericSnapshot = options.bars.value.map((bar) => ({ ...bar }))
    const window = deriveNewowTrendWindow(genericSnapshot)
    if (window === null) {
      error.value = 'NEWOW_WINDOW_INVALID'
      return
    }

    const controller = new AbortController()
    activeRequest = controller
    loading.value = true
    try {
      const response = await fetchDetail({
        product: identity.symbol,
        from: window.from,
        through: window.through,
      }, controller.signal)
      if (!isCurrent(requestGeneration, controller)) return
      if (!sameMarketBars(response, genericSnapshot) || !sameMarketBars(response, options.bars.value)) {
        error.value = 'NEWOW_DATA_IDENTITY_INVALID'
        return
      }
      data.value = response
    } catch (caught) {
      if (!isCurrent(requestGeneration, controller)) return
      data.value = null
      error.value = caught instanceof NewowTrendDetailRequestError
        ? caught.code
        : 'NEWOW_API_UNAVAILABLE'
    } finally {
      if (isCurrent(requestGeneration, controller)) {
        activeRequest = null
        loading.value = false
      }
    }
  }

  function isCurrent(requestGeneration: number, controller: AbortController): boolean {
    return !disposed
      && requestGeneration === generation
      && activeRequest === controller
      && !controller.signal.aborted
  }

  const requestIdentity = computed(() => {
    const identity = options.identity.value
    return identity === null ? '' : [identity.view, identity.symbol, identity.seriesKind,
      identity.frequency, identity.contract ?? ''].join(':')
  })
  const stopWatch = watch(
    [requestIdentity, () => options.bars.value],
    () => { void replace() },
    { immediate: true, deep: true, flush: 'sync' },
  )

  function dispose(): void {
    if (disposed) return
    disposed = true
    generation += 1
    activeRequest?.abort()
    activeRequest = null
    stopWatch()
    data.value = null
    loading.value = false
    error.value = null
  }

  return {
    data: readonly(data),
    loading: readonly(loading),
    error: readonly(error),
    dispose,
  }
}

function sameMarketBars(response: NewowTrendDetailResponse, generic: readonly BarData[]): boolean {
  return response.bars.length === generic.length && response.bars.every((bar, index) => {
    const other = generic[index]!
    return Date.parse(bar.bar_end) === Date.parse(other.time)
      && bar.trading_day === other.trading_day
      && bar.physical_contract === other.physicalContract
      && bar.open === other.open && bar.high === other.high && bar.low === other.low
      && bar.close === other.close && bar.volume === other.volume
      && bar.open_interest === (other.openInterest ?? null)
  })
}

function isNewowTrendIdentity(identity: MarketDetailIdentity | null): identity is MarketDetailIdentity {
  return identity !== null
    && identity.view === 'trend'
    && identity.seriesKind === 'actual_dominant'
    && identity.frequency === '1d'
    && /^[a-z]+$/.test(identity.symbol)
}

function deriveNewowTrendWindow(bars: readonly BarData[]): NewowTrendWindow | null {
  if (bars.length === 0) return null
  let previous: string | null = null
  for (const bar of bars) {
    const tradingDay = bar.trading_day
    if (tradingDay === undefined || !isIsoDay(tradingDay) || (previous !== null && tradingDay <= previous)) {
      return null
    }
    previous = tradingDay
  }
  return {
    from: bars[0]!.trading_day!,
    through: bars.at(-1)!.trading_day!,
  }
}

function isIsoDay(value: string): boolean {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false
  const parsed = new Date(`${value}T00:00:00Z`)
  return Number.isFinite(parsed.getTime()) && parsed.toISOString().slice(0, 10) === value
}
