import { shallowRef } from 'vue'

interface MarketHomeOptions<O, R> {
  fetchOverview: () => Promise<O>
  fetchRuntime: () => Promise<R>
  overviewCacheKey?: string
  overviewMaxAgeMs?: number
  now?: () => number
}

type ResourceError = 'request-failed' | 'typed-unavailable'

interface Resource<T> {
  data: ReturnType<typeof shallowRef<T | null>>
  loading: ReturnType<typeof shallowRef<boolean>>
  stale: ReturnType<typeof shallowRef<boolean>>
  unavailable: ReturnType<typeof shallowRef<boolean>>
  error: ReturnType<typeof shallowRef<ResourceError | null>>
  updatedAt: ReturnType<typeof shallowRef<number | null>>
  refresh: () => Promise<void>
  invalidate: () => void
}

interface ResourceState<T> {
  data: ReturnType<typeof shallowRef<T | null>>
  loading: ReturnType<typeof shallowRef<boolean>>
  stale: ReturnType<typeof shallowRef<boolean>>
  unavailable: ReturnType<typeof shallowRef<boolean>>
  error: ReturnType<typeof shallowRef<ResourceError | null>>
  updatedAt: ReturnType<typeof shallowRef<number | null>>
  generation: number
  inFlight: Promise<void> | null
}

let cachedOverview: { key: string; state: ResourceState<unknown> } | null = null

export function useMarketHome<O, R>(options: MarketHomeOptions<O, R>) {
  const now = options.now ?? Date.now
  const overview = createResource(options.fetchOverview, undefined, overviewState<O>(options.overviewCacheKey), now)
  const runtime = createResource(options.fetchRuntime, undefined, undefined, now)
  const overviewMaxAgeMs = options.overviewMaxAgeMs ?? 5 * 60_000
  let timer: ReturnType<typeof setInterval> | null = null
  let started = false

  async function refreshOverview() { await overview.refresh() }
  async function refreshOverviewIfExpired() {
    const acceptedAt = overview.updatedAt.value
    if (overview.data.value != null && acceptedAt != null && now() - acceptedAt <= overviewMaxAgeMs) return
    await overview.refresh()
  }
  function invalidateOverview() { overview.invalidate() }
  async function refreshRuntime() { await runtime.refresh() }
  async function refreshAll() { await Promise.all([overview.refresh(), runtime.refresh()]) }

  function onVisibilityChange() {
    if (document.visibilityState === 'visible') {
      startTimer()
      void Promise.all([refreshOverviewIfExpired(), refreshRuntime()])
    } else stopTimer()
  }

  function start() {
    if (typeof document === 'undefined' || started) return
    started = true
    document.addEventListener('visibilitychange', onVisibilityChange)
    if (document.visibilityState === 'visible') {
      startTimer()
      void Promise.all([refreshOverviewIfExpired(), refreshRuntime()])
    }
  }

  function startTimer() {
    if (timer !== null) return
    timer = setInterval(() => { void refreshRuntime() }, 60_000)
  }

  function stopTimer() {
    if (timer === null) return
    clearInterval(timer)
    timer = null
  }

  function dispose() {
    stopTimer()
    if (started && typeof document !== 'undefined') document.removeEventListener('visibilitychange', onVisibilityChange)
    started = false
  }

  return { overview, runtime, refreshOverview, refreshOverviewIfExpired, invalidateOverview, refreshRuntime, refreshAll, start, dispose }
}

function createResource<T>(
  fetch: () => Promise<T>,
  isTypedUnavailable?: (value: T) => boolean,
  existingState?: ResourceState<T>,
  now: () => number = Date.now,
): Resource<T> {
  const state = existingState ?? createResourceState<T>()
  async function refresh() {
    if (state.inFlight) return state.inFlight
    state.loading.value = true
    const generation = ++state.generation
    const request = fetch().then((value) => {
      if (generation !== state.generation) return
      if (isTypedUnavailable?.(value)) {
        state.stale.value = state.data.value !== null
        state.unavailable.value = true
        state.error.value = 'typed-unavailable'
        return
      }
      state.data.value = value
      state.updatedAt.value = now()
      state.stale.value = false
      state.unavailable.value = false
      state.error.value = null
    }).catch(() => {
      if (generation !== state.generation) return
      state.stale.value = state.data.value !== null
      state.unavailable.value = true
      state.error.value = 'request-failed'
    }).finally(() => {
      if (generation !== state.generation) return
      state.loading.value = false
      state.inFlight = null
    })
    state.inFlight = request
    return request
  }
  function invalidate() {
    state.generation += 1
    state.inFlight = null
    state.loading.value = false
    state.stale.value = state.data.value !== null
    state.updatedAt.value = null
  }
  return { data: state.data, loading: state.loading, stale: state.stale, unavailable: state.unavailable, error: state.error, updatedAt: state.updatedAt, refresh, invalidate }
}

function createResourceState<T>(): ResourceState<T> {
  return {
    data: shallowRef<T | null>(null),
    loading: shallowRef(false),
    stale: shallowRef(false),
    unavailable: shallowRef(false),
    error: shallowRef<ResourceError | null>(null),
    updatedAt: shallowRef<number | null>(null),
    generation: 0,
    inFlight: null,
  }
}

function overviewState<T>(key?: string): ResourceState<T> | undefined {
  if (!key) return undefined
  if (!cachedOverview || cachedOverview.key !== key) cachedOverview = { key, state: createResourceState<unknown>() }
  return cachedOverview.state as ResourceState<T>
}
