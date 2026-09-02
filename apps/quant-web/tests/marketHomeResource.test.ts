import assert from 'node:assert/strict'
import test from 'node:test'
import { useMarketHome } from '../src/composables/useMarketHome.ts'

test('loads exactly three resources once and coalesces duplicate in-flight refreshes', async () => {
  let resolveOverview!: (value: string) => void
  const pending = new Promise<string>((resolve) => { resolveOverview = resolve })
  const calls = { overview: 0, runtime: 0, events: 0 }
  const home = useMarketHome({
    fetchOverview: () => { calls.overview += 1; return pending },
    fetchRuntime: async () => { calls.runtime += 1; return 'runtime' },
    fetchEvents: async () => { calls.events += 1; return 'events' },
  })

  const first = home.refreshOverview()
  const duplicate = home.refreshOverview()
  resolveOverview('overview')
  await Promise.all([first, duplicate])
  await home.refreshAll()

  assert.deepEqual(calls, { overview: 2, runtime: 1, events: 1 })
  home.dispose()
})

test('retains the previous resource snapshot and marks only that resource stale after failure', async () => {
  let fail = false
  const home = useMarketHome({
    fetchOverview: async () => { if (fail) throw new Error('overview unavailable'); return 'old' },
    fetchRuntime: async () => 'runtime',
    fetchEvents: async () => 'events',
  })
  await home.refreshAll()
  fail = true
  await home.refreshOverview()

  assert.equal(home.overview.data.value, 'old')
  assert.equal(home.overview.stale.value, true)
  assert.equal(home.runtime.stale.value, false)
  assert.equal(home.events.stale.value, false)
  home.dispose()
})
