import { computed, readonly, ref, watch, type Ref } from 'vue'

import {
  useMarketSeries,
  type MarketSeriesIdentity,
  type MarketSeriesMutation,
} from './useMarketSeries.ts'
import type {
  BarData,
  DominantContractListResponse,
  DominantContractItem,
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
  productCatalog: Readonly<Ref<readonly DominantContractItem[]>>
  bars: Readonly<Ref<BarData[]>>
  mutation: Readonly<Ref<MarketSeriesMutation>>
  hasMoreBefore: Readonly<Ref<boolean>>
  research: Ref<ProductResearchResponse | null>
  researchError: Readonly<Ref<boolean>>
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
  const productCatalog = ref<DominantContractItem[]>([])
  let currentDominants: DominantContractListResponse = { items: [] }
  let dominantsRequest: Promise<DominantContractListResponse> | null = null
  let activeSeriesKey: string | null = null
  let activeResearchKey: string | null = null
  const currentResearch = ref<ProductResearchResponse | null>(null)
  const researchError = ref(false)
  let headerGeneration = 0
  let disposed = false
  const publicBars = computed(() => series.bars.value)
  const publicMutation = computed(() => series.mutation.value)

  function seriesKey(identity: MarketDetailIdentity): string {
    return [identity.symbol, identity.seriesKind, identity.contract ?? '', identity.frequency].join(':')
  }

  function researchKey(identity: MarketDetailIdentity): string {
    return [identity.symbol, identity.seriesKind, identity.contract ?? ''].join(':')
  }

  function canKeepHeader(previous: MarketDetailIdentity | null, next: MarketDetailIdentity): boolean {
    if (!previous || !state.value.header || seriesKey(previous) !== seriesKey(next)) return false
    return (previous.view === 'newow') === (next.view === 'newow')
  }

  async function loadDominants(): Promise<DominantContractListResponse> {
    if (currentDominants.items.length > 0) return currentDominants
    if (!dominantsRequest) {
      dominantsRequest = fetchDominants().then((value) => {
        currentDominants = value
        productCatalog.value = value.items
        return value
      }).finally(() => { dominantsRequest = null })
    }
    return dominantsRequest
  }

  function rebuildHeader(identity: MarketDetailIdentity): void {
    state.value.header = buildMarketDetailHeaderModel({
      identity,
      dominant: currentDominants.items.find((item) => item.product.toLowerCase() === identity.symbol.toLowerCase()) ?? null,
      bars: series.bars.value,
      research: currentResearch.value,
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
    const previousIdentity = state.value.identity
    const retainedHeader = canKeepHeader(previousIdentity, identity) ? state.value.header : null
    const usesGenericSeries = identity.view !== 'newow'
    const nextSeriesKey = seriesKey(identity)
    const reuseSeries = usesGenericSeries && activeSeriesKey === nextSeriesKey
    const nextResearchKey = researchKey(identity)
    const reuseResearch = usesGenericSeries && activeResearchKey === nextResearchKey && currentResearch.value !== null
    state.value = {
      route: { kind: 'valid', identity },
      identity,
      generation,
      header: retainedHeader,
      loading: retainedHeader === null,
      error: null,
    }
    headerGeneration = retainedHeader ? generation : 0
    if (!reuseResearch) {
      currentResearch.value = null
      activeResearchKey = null
      researchError.value = false
    }
    const metadataRequest = loadDominants().then(
      (value) => ({ ok: true as const, value }),
      () => ({ ok: false as const }),
    )
    if (!usesGenericSeries && previousIdentity?.view !== 'newow') {
      series.clearSeries()
      activeSeriesKey = null
    }
    const seriesRequest = usesGenericSeries
      ? reuseSeries ? Promise.resolve({ ok: true as const }) : series.replaceSeries(identity).then(
          () => ({ ok: true as const }),
          () => ({ ok: false as const }),
        )
      : Promise.resolve({ ok: true as const })
    const researchRequest = usesGenericSeries && !reuseResearch
      ? fetchResearch({
          symbol: identity.symbol,
          seriesKind: identity.seriesKind,
          contract: identity.seriesKind === 'contract' ? identity.contract : undefined,
        }).catch(() => null)
      : Promise.resolve(reuseResearch ? currentResearch.value : null)
    try {
      const [metadata, seriesResult] = await Promise.all([
        metadataRequest,
        seriesRequest,
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
      if (!seriesResult.ok) {
        activeSeriesKey = null
        state.value.header = null
        state.value.loading = false
        state.value.error = '详情行情加载失败'
        return
      }
      activeSeriesKey = usesGenericSeries ? nextSeriesKey : null
      headerGeneration = generation
      rebuildHeader(identity)
      state.value.loading = false
      const research = await researchRequest
      if (disposed || state.value.generation !== generation) return
      currentResearch.value = research
      researchError.value = research === null
      activeResearchKey = research === null ? null : nextResearchKey
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
    productCatalog: readonly(productCatalog),
    bars: publicBars,
    mutation: publicMutation,
    hasMoreBefore: readonly(series.hasMoreBefore),
    research: currentResearch,
    researchError: readonly(researchError),
    switchIdentity,
    loadMoreBefore,
    dispose,
  }
}
