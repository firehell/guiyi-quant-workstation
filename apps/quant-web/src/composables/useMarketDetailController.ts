import { computed, readonly, ref, watch, type Ref } from 'vue'

import {
  useMarketSeries,
  type MarketSeriesIdentity,
  type MarketSeriesMutation,
} from './useMarketSeries.ts'
import type {
  BarData,
  DominantContractListResponse,
  MarketOverlaySource,
  MarketReadState,
  ProductResearchResponse,
} from '../types/market.ts'
import type {
  MarketDetailHeaderModel,
  MarketDetailIdentity,
  MarketDetailRouteResult,
} from '../types/marketDetail.ts'
import { parseMarketDetailRoute } from '../utils/marketDetailRoute.ts'
import { buildMarketDetailHeaderModel } from '../utils/marketDetailViewModel.ts'

export interface MarketDetailControllerState {
  route: MarketDetailRouteResult
  identity: MarketDetailIdentity | null
  generation: number
  header: MarketDetailHeaderModel | null
  loading: boolean
  error: string | null
}

interface MarketDetailSeriesController {
  bars: Ref<BarData[]>
  hasMoreBefore: Ref<boolean>
  canonicalCoverage: Ref<{ start: string; end: string } | null>
  marketState: Ref<MarketReadState | null>
  liveUnavailable: Ref<boolean>
  overlaySource: Ref<MarketOverlaySource>
  mutation: Ref<MarketSeriesMutation>
  replaceSeries(identity: MarketSeriesIdentity): Promise<void>
  clearSeries(): void
  loadMoreBefore(): Promise<void>
  dispose(): void
}

export interface MarketDetailControllerDependencies {
  routeQuery?: () => Record<string, unknown>
  createSeries?: () => MarketDetailSeriesController
  fetchDominants?: () => Promise<DominantContractListResponse>
  fetchResearch?: (params: {
    symbol: string
    seriesKind: MarketDetailIdentity['seriesKind']
    contract?: string
  }) => Promise<ProductResearchResponse>
}

function browserRouteQuery(): Record<string, string> {
  if (typeof window === 'undefined') return {}
  return Object.fromEntries(new URLSearchParams(window.location.search))
}

async function defaultFetchDominants(): Promise<DominantContractListResponse> {
  const { getMarketDominants } = await import('../api/market.ts')
  return getMarketDominants()
}

async function defaultFetchResearch(params: {
  symbol: string
  seriesKind: MarketDetailIdentity['seriesKind']
  contract?: string
}): Promise<ProductResearchResponse> {
  const { getProductResearch } = await import('../api/market.ts')
  return getProductResearch(params)
}

export function useMarketDetailController(
  dependencies: MarketDetailControllerDependencies = {},
): {
  state: Readonly<Ref<MarketDetailControllerState>>
  bars: Readonly<Ref<BarData[]>>
  mutation: Readonly<Ref<MarketSeriesMutation>>
  switchIdentity(identity: MarketDetailIdentity): Promise<void>
  loadMoreBefore(): Promise<void>
  dispose(): void
} {
  const createSeries = dependencies.createSeries ?? (() => useMarketSeries())
  const series = createSeries()
  const fetchDominants = dependencies.fetchDominants ?? defaultFetchDominants
  const fetchResearch = dependencies.fetchResearch ?? defaultFetchResearch
  const route = parseMarketDetailRoute((dependencies.routeQuery ?? browserRouteQuery)())
  const state = ref<MarketDetailControllerState>({
    route,
    identity: null,
    generation: 0,
    header: null,
    loading: false,
    error: null,
  })
  let currentDominants: DominantContractListResponse = { items: [] }
  let currentResearch: ProductResearchResponse | null = null
  let headerGeneration = 0
  let disposed = false
  const publicBars = computed(() => series.bars.value)
  const publicMutation = computed(() => series.mutation.value)

  function rebuildHeader(identity: MarketDetailIdentity): void {
    state.value.header = buildMarketDetailHeaderModel({
      identity,
      dominant: currentDominants.items.find((item) => item.product.toLowerCase() === identity.symbol.toLowerCase()) ?? null,
      bars: series.bars.value,
      research: currentResearch,
      marketState: series.marketState.value,
      overlaySource: series.overlaySource.value,
      canonicalCoverage: series.canonicalCoverage.value,
      hasMoreBefore: series.hasMoreBefore.value,
      stale: series.liveUnavailable.value,
    })
  }

  const stopSeriesWatch = watch(
    [
      series.mutation,
      series.marketState,
      series.liveUnavailable,
      series.overlaySource,
      series.canonicalCoverage,
      series.hasMoreBefore,
    ],
    () => {
      const identity = state.value.identity
      if (disposed || !identity || headerGeneration !== state.value.generation || !state.value.header) return
      rebuildHeader(identity)
    },
  )

  async function switchIdentity(identity: MarketDetailIdentity): Promise<void> {
    const generation = state.value.generation + 1
    state.value = {
      route: { kind: 'valid', identity },
      identity,
      generation,
      header: null,
      loading: true,
      error: null,
    }
    headerGeneration = 0
    currentDominants = { items: [] }
    currentResearch = null
    const metadataRequest = fetchDominants().then(
      (value) => ({ ok: true as const, value }),
      () => ({ ok: false as const }),
    )
    const researchRequest = fetchResearch({
      symbol: identity.symbol,
      seriesKind: identity.seriesKind,
      contract: identity.seriesKind === 'contract' ? identity.contract : undefined,
    }).catch(() => null)
    try {
      const [metadata] = await Promise.all([
        metadataRequest,
        series.replaceSeries(identity),
      ])
      if (disposed || state.value.generation !== generation) return
      const hasCurrentProduct = metadata.ok && metadata.value.items.some(
        (item) => item.product.toLowerCase() === identity.symbol.toLowerCase(),
      )
      if (!metadata.ok || !hasCurrentProduct) {
        series.clearSeries()
        state.value.header = null
        state.value.loading = false
        state.value.error = '品种元数据不可用'
        return
      }
      currentDominants = metadata.value
      headerGeneration = generation
      rebuildHeader(identity)
      state.value.loading = false
      const research = await researchRequest
      if (disposed || state.value.generation !== generation) return
      currentResearch = research
      rebuildHeader(identity)
    } catch {
      if (disposed || state.value.generation !== generation) return
      state.value.header = null
      state.value.loading = false
      state.value.error = '详情行情加载失败'
    }
  }

  async function loadMoreBefore(): Promise<void> {
    const generation = state.value.generation
    const identity = state.value.identity
    if (!identity || disposed) return
    await series.loadMoreBefore()
    if (disposed || state.value.generation !== generation) return
    rebuildHeader(identity)
  }

  function dispose(): void {
    if (disposed) return
    disposed = true
    state.value.generation += 1
    stopSeriesWatch()
    series.dispose()
  }

  return {
    state: readonly(state),
    bars: publicBars,
    mutation: publicMutation,
    switchIdentity,
    loadMoreBefore,
    dispose,
  }
}
