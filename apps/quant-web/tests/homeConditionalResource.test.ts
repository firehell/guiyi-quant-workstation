import assert from 'node:assert/strict'
import test from 'node:test'
import { createConditionalResource } from '../src/utils/homeConditionalResource.ts'

test('conditional reads propagate cancellation and never retain an aborted body', async () => {
  const controller = new AbortController()
  const read = createConditionalResource((_etag, signal) => new Promise((_resolve, reject) => {
    assert.equal(signal, controller.signal)
    signal!.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')), { once: true })
  }), String)
  const result = read(controller.signal); controller.abort()
  await assert.rejects(result, { name: 'AbortError' })
})

test('first validation is unconditional and subsequent 304 retains validated body without normalization', async () => {
  const etags: Array<string | undefined> = []
  let normalized = 0
  const read = createConditionalResource(async etag => { etags.push(etag); return etag ? { status: 304, data: undefined } : { status: 200, data: { rows: ['rb'] }, etag: 'one' } }, value => { normalized++; return value as { rows: string[] } })
  const initial = await read(); initial.rows.push('foreign')
  assert.deepEqual(await read(), { rows: ['rb'] })
  assert.deepEqual(etags, [undefined, 'one'])
  assert.equal(normalized, 1)
})

test('unexpected 304 and corrupt 200 never seed conditional authority', async () => {
  let status = 304
  const etags: Array<string | undefined> = []
  const read = createConditionalResource(async etag => { etags.push(etag); return { status, data: 'bad', etag: 'corrupt' } }, () => { throw Error('invalid') })
  await assert.rejects(read(), /WITHOUT_VALIDATED/)
  status = 200
  await assert.rejects(read(), /invalid/)
  await assert.rejects(read(), /invalid/)
  assert.deepEqual(etags, [undefined, undefined, undefined])
})

test('a late HTTP response cannot replace the latest conditional validator', async () => {
  const requests: Array<{ etag?: string; resolve: (value: { status: number; data: unknown; etag: string }) => void }> = []
  const read = createConditionalResource(etag => new Promise(resolve => requests.push({ etag, resolve })), value => value)
  const old = read(), fresh = read()
  requests[1]!.resolve({ status: 200, data: 'new', etag: 'new' }); await fresh
  requests[0]!.resolve({ status: 200, data: 'old', etag: 'old' }); await old
  const next = read()
  assert.equal(requests[2]!.etag, 'new')
  requests[2]!.resolve({ status: 304, data: null, etag: 'new' })
  assert.equal(await next, 'new')
})
