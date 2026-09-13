import assert from 'node:assert/strict'
import test from 'node:test'
import { useMarketHome } from '../src/composables/useMarketHome.ts'

test('loads only overview and runtime and coalesces duplicate in-flight refreshes', async () => {
  let resolveOverview!: (value: string) => void
  const pending = new Promise<string>((resolve) => { resolveOverview = resolve })
  const calls = { overview: 0, runtime: 0 }
  const home = useMarketHome({
    fetchOverview: () => { calls.overview += 1; return pending },
    fetchRuntime: async () => { calls.runtime += 1; return 'runtime' },
  })

  const first = home.refreshOverview()
  const duplicate = home.refreshOverview()
  resolveOverview('overview')
  await Promise.all([first, duplicate])
  await home.refreshAll()

  assert.deepEqual(calls, { overview: 2, runtime: 1 })
  home.dispose()
})

test('retains the previous resource snapshot and marks only that resource stale after failure', async () => {
  let fail = false
  const home = useMarketHome({
    fetchOverview: async () => { if (fail) throw new Error('overview unavailable'); return 'old' },
    fetchRuntime: async () => 'runtime',
  })
  await home.refreshAll()
  fail = true
  await home.refreshOverview()

  assert.equal(home.overview.data.value, 'old')
  assert.equal(home.overview.stale.value, true)
  assert.equal(home.runtime.stale.value, false)
  home.dispose()
})

test('reuses a fresh accepted overview immediately after dispose and reentry', async () => {
  let now = 1_000
  let calls = 0
  const options = () => ({
    fetchOverview: async () => { calls += 1; return `overview-${calls}` },
    fetchRuntime: async () => 'runtime',
    overviewCacheKey: 'resource-reentry',
    overviewMaxAgeMs: 5 * 60_000,
    now: () => now,
  })
  const first = useMarketHome(options())
  await first.refreshOverview()
  first.dispose()

  now += 60_000
  const second = useMarketHome(options())
  assert.equal(second.overview.data.value, 'overview-1')
  await second.refreshOverviewIfExpired()

  assert.equal(calls, 1)
  second.dispose()
})

test('keeps an expired overview visible while one background refresh replaces it', async () => {
  let now = 1_000
  let calls = 0
  let resolveRefresh!: (value: string) => void
  const home = useMarketHome({
    fetchOverview: () => {
      calls += 1
      if (calls === 1) return Promise.resolve('accepted')
      return new Promise<string>((resolve) => { resolveRefresh = resolve })
    },
    fetchRuntime: async () => 'runtime',
    overviewCacheKey: 'resource-expiry',
    overviewMaxAgeMs: 20_000,
    now: () => now,
  })
  await home.refreshOverview()
  now += 20_001

  const first = home.refreshOverviewIfExpired()
  const duplicate = home.refreshOverviewIfExpired()
  assert.equal(home.overview.data.value, 'accepted')
  assert.equal(home.overview.loading.value, true)
  assert.equal(calls, 2)
  resolveRefresh('renewed')
  await Promise.all([first, duplicate])

  assert.equal(home.overview.data.value, 'renewed')
  assert.equal(calls, 2)
  home.dispose()
})

test('invalidating an identity prevents its late response from replacing the new snapshot', async () => {
  const resolvers: Array<(value: string) => void> = []
  const home = useMarketHome({
    fetchOverview: () => new Promise<string>((resolve) => { resolvers.push(resolve) }),
    fetchRuntime: async () => 'runtime',
    overviewCacheKey: 'resource-generation',
  })

  const oldRequest = home.refreshOverview()
  home.invalidateOverview()
  const newRequest = home.refreshOverview()
  resolvers[1]('new-identity')
  await newRequest
  resolvers[0]('old-identity')
  await oldRequest

  assert.equal(home.overview.data.value, 'new-identity')
  home.dispose()
})

test('start and dispose balance visibility listeners and polling timers across reentry', () => {
  const originalDocument = Object.getOwnPropertyDescriptor(globalThis, 'document')
  const originalSetInterval = globalThis.setInterval
  const originalClearInterval = globalThis.clearInterval
  const listeners = new Set<EventListener>()
  let createdTimers = 0
  let clearedTimers = 0
  Object.defineProperty(globalThis, 'document', {
    configurable: true,
    value: {
      visibilityState: 'hidden',
      addEventListener: (_type: string, listener: EventListener) => listeners.add(listener),
      removeEventListener: (_type: string, listener: EventListener) => listeners.delete(listener),
    },
  })
  Object.assign(globalThis, {
    setInterval: (() => { createdTimers += 1; return createdTimers }) as typeof setInterval,
    clearInterval: (() => { clearedTimers += 1 }) as typeof clearInterval,
  })
  const create = () => useMarketHome({
    fetchOverview: async () => 'overview', fetchRuntime: async () => 'runtime',
  })

  try {
    const first = create()
    first.start()
    first.start()
    assert.equal(listeners.size, 1)
    first.dispose()
    assert.equal(listeners.size, 0)

    Object.assign(globalThis.document, { visibilityState: 'visible' })
    const second = create()
    second.start()
    second.start()
    assert.equal(listeners.size, 1)
    assert.equal(createdTimers, 1)
    second.dispose()
    assert.equal(listeners.size, 0)
    assert.equal(clearedTimers, 1)
  } finally {
    Object.assign(globalThis, { setInterval: originalSetInterval, clearInterval: originalClearInterval })
    if (originalDocument) Object.defineProperty(globalThis, 'document', originalDocument)
    else Reflect.deleteProperty(globalThis, 'document')
  }
})
