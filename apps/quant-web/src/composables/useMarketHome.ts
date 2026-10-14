import { shallowRef } from 'vue'
import type { HomeSnapshotCache } from '../utils/marketHomePersistence.ts'

interface MarketHomeOptions<O, R, D> {
  fetchOverview: () => Promise<O>
  fetchDirectory: () => Promise<D>
  fetchRuntime: () => Promise<R>
  overviewCacheKey?: string
  overviewMaxAgeMs?: number
  now?: () => number
  persistence?: HomeSnapshotCache
  validateOverview?: (value: unknown) => O
  validateDirectory?: (value: unknown) => D
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

let cachedHome: { key: string; overview: ResourceState<unknown>; directory: ResourceState<unknown> } | null = null

export function useMarketHome<O, R, D>(options: MarketHomeOptions<O, R, D>) {
  const now = options.now ?? Date.now
  const overview = createResource(options.fetchOverview, undefined, cachedState<O>('overview', options.overviewCacheKey), now, value => options.persistence?.put('overview', value))
  const directory = createResource(options.fetchDirectory, undefined, cachedState<D>('directory', options.overviewCacheKey), now, value => options.persistence?.put('directory', value))
  const restored = shallowRef(false)
  const restore = async () => {
    if (restored.value || !options.persistence) return
    await options.persistence.restore()
    for (const [key, resource, validate] of [['overview', overview, options.validateOverview], ['directory', directory, options.validateDirectory]] as const) {
      if (resource.data.value != null || !validate) continue
      const snapshot = options.persistence.peek(key)
      if (!snapshot) continue
      try {
        resource.data.value = validate(snapshot.value) as O & D
        resource.updatedAt.value = snapshot.savedAt
        resource.stale.value = true
      } catch { await options.persistence.discard(key) }
    }
    restored.value = true
  }
  const runtime = createResource(options.fetchRuntime, undefined, undefined, now)
  const overviewMaxAgeMs = options.overviewMaxAgeMs ?? 5 * 60_000
  let timer: ReturnType<typeof setInterval> | null = null
  let started = false

  async function refreshOverview() { if (options.persistence) await restore(); await overview.refresh() }
  async function refreshOverviewIfExpired() {
    await refreshIfExpired(overview)
  }
  async function refreshIfExpired<T>(resource: Resource<T>) {
    if (options.persistence) await restore()
    const acceptedAt = resource.updatedAt.value
    if (!resource.stale.value && !resource.unavailable.value && resource.data.value != null && acceptedAt != null && now() - acceptedAt <= overviewMaxAgeMs) return
    await resource.refresh()
  }
  async function refreshDirectoryIfExpired() { await refreshIfExpired(directory) }
  function invalidateOverview() { overview.invalidate() }
  async function refreshRuntime() { await runtime.refresh() }
  async function refreshAll() {
    // Runtime has its own loading/error state; its health scan must not hold
    // completed market facts or the following strategy refresh behind it.
    void runtime.refresh()
    if (options.persistence) await restore()
    await Promise.all([overview.refresh(), directory.refresh()])
  }

  function onVisibilityChange() {
    if (document.visibilityState === 'visible') {
      startTimer()
      void Promise.all([refreshOverviewIfExpired(), refreshRuntime(), refreshDirectoryIfExpired()])
    } else stopTimer()
  }

  function start() {
    if (typeof document === 'undefined' || started) return
    started = true
    document.addEventListener('visibilitychange', onVisibilityChange)
    if (document.visibilityState === 'visible') {
      startTimer()
      void Promise.all([refreshOverviewIfExpired(), refreshRuntime(), refreshDirectoryIfExpired()])
    }
  }

  function startTimer() {
    if (timer !== null) return
    timer = setInterval(() => { void Promise.all([refreshOverviewIfExpired(), refreshRuntime(), refreshDirectoryIfExpired()]) }, 60_000)
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

  return { restored, restore, overview, runtime, directory, refreshDirectoryIfExpired, refreshOverview, refreshOverviewIfExpired, invalidateOverview, refreshRuntime, refreshAll, start, dispose }
}

function createResource<T>(
  fetch: () => Promise<T>,
  isTypedUnavailable?: (value: T) => boolean,
  existingState?: ResourceState<T>,
  now: () => number = Date.now,
  save?: (value: T) => unknown,
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
      void save?.(value)
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

function cachedState<T>(resource: 'overview' | 'directory', key?: string): ResourceState<T> | undefined {
  if (!key) return undefined
  if (!cachedHome || cachedHome.key !== key) cachedHome = {
    key, overview: createResourceState<unknown>(), directory: createResourceState<unknown>(),
  }
  return cachedHome[resource] as ResourceState<T>
}
