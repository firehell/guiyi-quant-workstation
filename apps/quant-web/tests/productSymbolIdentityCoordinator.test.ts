import assert from 'node:assert/strict'
import test from 'node:test'
import { nextTick } from 'vue'

import { useProductSymbolIdentityCoordinator } from '../src/composables/useProductSymbolIdentityCoordinator.ts'


test('invalidates facts synchronously and waits for the accepted Market identity', async () => {
  const calls: string[] = []
  const market = deferred<boolean>()
  const coordinator = useProductSymbolIdentityCoordinator({
    invalidateFacts: () => calls.push('invalidate'),
    refreshMarket: () => {
      calls.push('market')
      return market.promise
    },
    refreshFacts: () => [
      Promise.resolve().then(() => { calls.push('research') }),
      Promise.resolve().then(() => { calls.push('subing') }),
      Promise.resolve().then(() => { calls.push('alerts') }),
      Promise.resolve().then(() => { calls.push('events') }),
    ],
    rejectFacts: () => calls.push('reject'),
  })

  const synchronization = coordinator.synchronize()

  assert.deepEqual(calls, ['invalidate', 'market'])
  assert.equal(coordinator.synchronizing.value, true)
  market.resolve(true)
  await synchronization

  assert.deepEqual(calls, ['invalidate', 'market', 'research', 'subing', 'alerts', 'events'])
  assert.equal(coordinator.synchronizing.value, false)
  coordinator.dispose()
})

test('rejects facts without refreshing them when Market identity is unavailable', async () => {
  let factRefreshes = 0
  let rejections = 0
  const coordinator = useProductSymbolIdentityCoordinator({
    invalidateFacts: () => undefined,
    refreshMarket: async () => false,
    refreshFacts: () => {
      factRefreshes += 1
      return []
    },
    rejectFacts: () => { rejections += 1 },
  })

  await coordinator.synchronize()

  assert.equal(factRefreshes, 0)
  assert.equal(rejections, 1)
  assert.equal(coordinator.synchronizing.value, false)
  coordinator.dispose()
})

test('allows only the final AG generation to refresh facts across AG to JM to AG', async () => {
  const marketRequests = [deferred<boolean>(), deferred<boolean>()]
  const factRefreshes: number[] = []
  let request = 0
  const coordinator = useProductSymbolIdentityCoordinator({
    invalidateFacts: () => undefined,
    refreshMarket: () => marketRequests[request++].promise,
    refreshFacts: () => {
      factRefreshes.push(request)
      return []
    },
    rejectFacts: () => undefined,
  })

  const jm = coordinator.synchronize()
  const finalAg = coordinator.synchronize()
  marketRequests[1].resolve(true)
  await finalAg
  marketRequests[0].resolve(true)
  await jm

  assert.deepEqual(factRefreshes, [2])
  assert.equal(coordinator.synchronizing.value, false)
  coordinator.dispose()
})

test('dispose prevents late Market completions from changing fact state', async () => {
  const market = deferred<boolean>()
  let factRefreshes = 0
  let rejections = 0
  const coordinator = useProductSymbolIdentityCoordinator({
    invalidateFacts: () => undefined,
    refreshMarket: () => market.promise,
    refreshFacts: () => {
      factRefreshes += 1
      return []
    },
    rejectFacts: () => { rejections += 1 },
  })

  const synchronization = coordinator.synchronize()
  coordinator.dispose()
  market.resolve(false)
  await synchronization
  await nextTick()

  assert.equal(factRefreshes, 0)
  assert.equal(rejections, 0)
  assert.equal(coordinator.synchronizing.value, false)
})

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((resolver) => { resolve = resolver })
  return { promise, resolve }
}
