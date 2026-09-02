import { shallowRef } from 'vue'

interface MarketHomeOptions<O, R, E> {
  fetchOverview: () => Promise<O>
  fetchRuntime: () => Promise<R>
  fetchEvents: () => Promise<E>
  isEventUnavailable?: (value: E) => boolean
}

type ResourceError = 'request-failed' | 'typed-unavailable'

interface Resource<T> {
  data: ReturnType<typeof shallowRef<T | null>>
  loading: ReturnType<typeof shallowRef<boolean>>
  stale: ReturnType<typeof shallowRef<boolean>>
  unavailable: ReturnType<typeof shallowRef<boolean>>
  error: ReturnType<typeof shallowRef<ResourceError | null>>
  refresh: () => Promise<void>
}

export function useMarketHome<O, R, E>(options: MarketHomeOptions<O, R, E>) {
  const overview = createResource(options.fetchOverview)
  const runtime = createResource(options.fetchRuntime)
  const events = createResource(options.fetchEvents, options.isEventUnavailable)
  let timer: ReturnType<typeof setInterval> | null = null

  async function refreshOverview() { await overview.refresh() }
  async function refreshRuntimeAndEvents() { await Promise.all([runtime.refresh(), events.refresh()]) }
  async function refreshAll() { await Promise.all([overview.refresh(), runtime.refresh(), events.refresh()]) }

  function onVisibilityChange() {
    if (document.visibilityState === 'visible') {
      startTimer()
      void refreshAll()
    } else stopTimer()
  }

  function start() {
    if (typeof document === 'undefined') return
    document.addEventListener('visibilitychange', onVisibilityChange)
    if (document.visibilityState === 'visible') {
      startTimer()
      void refreshAll()
    }
  }

  function startTimer() {
    if (timer !== null) return
    timer = setInterval(() => { void refreshRuntimeAndEvents() }, 60_000)
  }

  function stopTimer() {
    if (timer === null) return
    clearInterval(timer)
    timer = null
  }

  function dispose() {
    stopTimer()
    if (typeof document !== 'undefined') document.removeEventListener('visibilitychange', onVisibilityChange)
  }

  return { overview, runtime, events, refreshOverview, refreshRuntimeAndEvents, refreshAll, start, dispose }
}

function createResource<T>(fetch: () => Promise<T>, isTypedUnavailable?: (value: T) => boolean): Resource<T> {
  const data = shallowRef<T | null>(null)
  const loading = shallowRef(false)
  const stale = shallowRef(false)
  const unavailable = shallowRef(false)
  const error = shallowRef<ResourceError | null>(null)
  let inFlight: Promise<void> | null = null
  async function refresh() {
    if (inFlight) return inFlight
    loading.value = true
    inFlight = fetch().then((value) => {
      if (isTypedUnavailable?.(value)) {
        stale.value = data.value !== null
        unavailable.value = true
        error.value = 'typed-unavailable'
        return
      }
      data.value = value
      stale.value = false
      unavailable.value = false
      error.value = null
    }).catch(() => {
      stale.value = data.value !== null
      unavailable.value = true
      error.value = 'request-failed'
    }).finally(() => { loading.value = false; inFlight = null })
    return inFlight
  }
  return { data, loading, stale, unavailable, error, refresh }
}
