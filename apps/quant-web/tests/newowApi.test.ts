import assert from 'node:assert/strict'
import test from 'node:test'

import {
  getNewowTrendDetail,
  NewowTrendDetailRequestError,
} from '../src/api/newow.ts'
import { minimalNewowWire } from './helpers/newowWire.ts'

const FROM = '2026-08-14'
const THROUGH = '2026-08-15'

test('uses the single Newow detail endpoint with its fixed read-only query and normalizes the wire payload', async () => {
  const calls: Array<{ path: string; config: unknown }> = []
  const controller = new AbortController()
  const result = await getNewowTrendDetail(
    { product: 'jm', from: FROM, through: THROUGH },
    {
      signal: controller.signal,
      request: async (path, config) => {
        calls.push({ path, config })
        return minimalNewowWire('jm', FROM, THROUGH)
      },
    },
  )

  assert.deepEqual(calls, [{
    path: '/market/newow/trend-detail',
    config: {
      params: {
        product: 'jm',
        from: FROM,
        through: THROUGH,
        frequency: '1d',
        series_kind: 'actual_dominant',
      },
      signal: controller.signal,
    },
  }])
  assert.equal(result.instrument.product, 'jm')
  assert.equal(result.meta.frequency, '1d')
  assert.equal(Object.isFrozen(result), true)
})

test('maps every transport failure to API unavailable and every invalid response to response invalid', async () => {
  await assert.rejects(
    getNewowTrendDetail({ product: 'jm', from: FROM, through: THROUGH }, {
      request: async () => { throw new Error('/Users/private/database password leaked') },
    }),
    safeFailure('NEWOW_API_UNAVAILABLE'),
  )
  await assert.rejects(
    getNewowTrendDetail({ product: 'jm', from: FROM, through: THROUGH }, {
      request: async () => ({ unexpected: 'payload' }),
    }),
    safeFailure('NEWOW_RESPONSE_INVALID'),
  )
})

test('exposes only strict known detail.code values from 409 and 422 responses', async () => {
  const cases = [
    [422, 'NEWOW_INVALID_PRODUCT'],
    [422, 'NEWOW_INVALID_RANGE'],
    [422, 'NEWOW_RANGE_TOO_LARGE'],
    [409, 'NEWOW_DATA_IDENTITY_INVALID'],
    [409, 'NEWOW_DATA_UNAVAILABLE'],
    [409, 'NEWOW_DATA_OUT_OF_ORDER'],
  ] as const
  for (const [status, code] of cases) {
    await assert.rejects(
      getNewowTrendDetail({ product: 'jm', from: FROM, through: THROUGH }, {
        request: async () => { throw { response: { status, data: { detail: { code, hidden: '/secret' } } } } },
      }),
      safeFailure(code),
    )
  }
})

test('rejects unknown, misplaced, wrong-status, or hostile HTTP details as API unavailable', async () => {
  const failures: unknown[] = [
    { response: { status: 409, data: { detail: { code: 'NEWOW_INTERNAL_SECRET' } } } },
    { response: { status: 409, data: { code: 'NEWOW_INVALID_RANGE' } } },
    { response: { status: 409, data: { detail: { code: 'NEWOW_INVALID_RANGE' } } } },
    { response: { status: 422, data: { detail: { code: 'NEWOW_DATA_UNAVAILABLE' } } } },
    { response: { status: 500, data: { detail: { code: 'NEWOW_DATA_UNAVAILABLE' } } } },
    { response: { status: 422, data: { detail: 'NEWOW_INVALID_RANGE' } } },
    { response: { status: 422, get data() { throw new Error('secret getter') } } },
  ]
  for (const failure of failures) {
    await assert.rejects(
      getNewowTrendDetail({ product: 'jm', from: FROM, through: THROUGH }, {
        request: async () => { throw failure },
      }),
      safeFailure('NEWOW_API_UNAVAILABLE'),
    )
  }
})

function safeFailure(code: string) {
  return (error: unknown) => {
    assert.equal(error instanceof NewowTrendDetailRequestError, true)
    assert.equal((error as NewowTrendDetailRequestError).code, code)
    assert.equal((error as Error).message, code)
    assert.doesNotMatch(String(error), /private|password|secret|database/i)
    return true
  }
}
