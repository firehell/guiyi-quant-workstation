import assert from 'node:assert/strict'
import test from 'node:test'
import { useMarketHome } from '../src/composables/useMarketHome.ts'

test('loads independent resources and coalesces duplicate in-flight refreshes', async () => {
  let resolveOverview!: (value: string) => void
  const pending = new Promise<string>((resolve) => { resolveOverview = resolve })
  const calls = { overview: 0, runtime: 0 }
  const home = useMarketHome({
    fetchDirectory: async () => 'directory',
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
    fetchDirectory: async () => 'directory',
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
    fetchDirectory: async () => 'directory',
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
    fetchDirectory: async () => 'directory',
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
    fetchDirectory: async () => 'directory',
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
    fetchDirectory: async () => 'directory',
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

test('visible timer recovers failed overview and renews expired snapshots without duplicate reads', async () => {
  const originalDocument = Object.getOwnPropertyDescriptor(globalThis, 'document')
  const originalSetInterval = globalThis.setInterval
  const originalClearInterval = globalThis.clearInterval
  let tick = () => {}
  let now = 0
  let calls = 0
  let fail = true
  let resolvePending!: (value: string) => void
  const flush = async () => { for (let i = 0; i < 8; i++) await Promise.resolve() }
  Object.defineProperty(globalThis, 'document', { configurable: true, value: {
    visibilityState: 'visible', addEventListener() {}, removeEventListener() {},
  } })
  Object.assign(globalThis, {
    setInterval: ((callback: () => void) => { tick = callback; return 1 }) as unknown as typeof setInterval,
    clearInterval: (() => {}) as typeof clearInterval,
  })
  const home = useMarketHome({
    fetchDirectory: async () => 'directory',
    fetchOverview: () => {
      calls += 1
      if (fail) return Promise.reject(new Error('offline'))
      return new Promise<string>((resolve) => { resolvePending = resolve })
    },
    fetchRuntime: async () => 'runtime', now: () => now,
  })
  try {
    home.start()
    await flush()
    assert.equal(home.overview.unavailable.value, true)
    fail = false
    now = 60_000
    tick(); await flush()
    assert.equal(calls, 2)
    now += 60_000
    tick(); await flush()
    assert.equal(calls, 2)
    resolvePending('recovered'); await flush()
    assert.equal(home.overview.data.value, 'recovered')
    assert.equal(home.overview.unavailable.value, false)
    now += 60_000
    tick(); await flush()
    assert.equal(calls, 2)
    now += 300_001
    tick(); await flush()
    assert.equal(calls, 3)
    assert.equal(home.overview.data.value, 'recovered')
    resolvePending('renewed'); await flush()
    assert.equal(home.overview.data.value, 'renewed')
  } finally {
    home.dispose()
    Object.assign(globalThis, { setInterval: originalSetInterval, clearInterval: originalClearInterval })
    if (originalDocument) Object.defineProperty(globalThis, 'document', originalDocument)
    else Reflect.deleteProperty(globalThis, 'document')
  }
})

test('directory loads once independently of a pending overview and keeps its accepted snapshot on failure', async () => {
  let finishOverview!: (value: string) => void
  let calls = 0
  let fail = false
  const home = useMarketHome({
    fetchOverview: () => new Promise<string>(resolve => { finishOverview = resolve }),
    fetchRuntime: async () => 'runtime',
    fetchDirectory: async () => { calls += 1; if (fail) throw new Error('offline'); return ['au', 'jm'] },
  })
  const first = home.refreshAll()
  const second = home.refreshAll()
  for (let i = 0; i < 8; i++) await Promise.resolve()
  assert.equal(calls, 1)
  assert.deepEqual(home.directory.data.value, ['au', 'jm'])
  assert.equal(home.overview.loading.value, true)
  finishOverview('overview'); await Promise.all([first, second])
  fail = true
  await home.directory.refresh()
  assert.deepEqual(home.directory.data.value, ['au', 'jm'])
  assert.equal(home.directory.stale.value, true)
  assert.equal(home.overview.stale.value, false)
  home.dispose()
})
