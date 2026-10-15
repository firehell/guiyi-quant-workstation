import assert from 'node:assert/strict'
import test from 'node:test'
import { useIdentityBoundResource } from '../src/composables/useIdentityBoundResource.ts'

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (error: Error) => void
  const promise = new Promise<T>((done, fail) => { resolve = done; reject = fail })
  return { promise, resolve, reject }
}

test('a late failure cannot clear a newer accepted identity', async () => {
  const old = deferred<number>()
  const resource = useIdentityBoundResource({
    key: (identity: string) => identity,
    load: (identity: string) => identity === 'old' ? old.promise : Promise.resolve(42),
    project: (wire: number) => wire,
  })
  const pending = resource.refresh('old')
  await resource.refresh('new')
  old.reject(new Error('old timeout'))
  await pending
  assert.equal(resource.value.value, 42)
  assert.equal(resource.unavailable.value, false)
})

test('two refreshes for the same identity only accept the newest response', async () => {
  const first = deferred<number>()
  let calls = 0
  const resource = useIdentityBoundResource({
    key: (identity: string) => identity,
    load: () => ++calls === 1 ? first.promise : Promise.resolve(2),
    project: (wire: number) => wire,
  })
  const pending = resource.refresh('jm')
  await resource.refresh('jm')
  first.resolve(1)
  await pending
  assert.equal(resource.value.value, 2)
})

test('projection errors fail closed and a subsequent valid read recovers', async () => {
  let wire = -1
  const resource = useIdentityBoundResource({
    key: (identity: string) => identity,
    load: async () => wire,
    project: (value: number) => { if (value < 0) throw new Error('invalid wire'); return value },
  })
  await resource.refresh('jm')
  assert.equal(resource.value.value, null)
  assert.equal(resource.unavailable.value, true)
  wire = 0
  await resource.refresh('jm')
  assert.equal(resource.value.value, 0)
  assert.equal(resource.unavailable.value, false)
})

test('dispose invalidates facts, ignores pending work and never starts another read', async () => {
  const response = deferred<number>()
  let calls = 0
  const resource = useIdentityBoundResource({
    key: (identity: string) => identity,
    load: () => { calls++; return response.promise },
    project: (wire: number) => wire,
  })
  const pending = resource.refresh('jm')
  resource.dispose()
  response.resolve(42)
  await pending
  await resource.refresh('rb')
  assert.equal(calls, 1)
  assert.equal(resource.value.value, null)
  assert.equal(resource.unavailable.value, true)
})
