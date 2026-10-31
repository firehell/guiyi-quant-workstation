import assert from 'node:assert/strict'
import test from 'node:test'
import { classifyTransportError } from '../src/api/newowProduct.ts'
import { newowErrorDisplay } from '../src/utils/newowDataDiagnostics.ts'

test('reference status preserves public cause and validates cutoff metadata', () => {
  const failure = (status: unknown) => ({ response: { status: 503, data: { detail: {
    code: 'REFERENCE_UPDATE_PENDING', reference_status: status,
  } } } })
  const error = classifyTransportError(failure({reason: 'REFERENCE_UPDATE_PENDING', result_through: '2026-10-26T07:00:00Z', market_through: '2026-10-30T07:00:00Z'}))
  assert.equal(error.code, 'REFERENCE_UPDATE_PENDING')
  assert.equal(error.classification, 'unavailable')
  assert.match(newowErrorDisplay(error.message)!, /参考结果更新中.*2026-10-26.*2026-10-30/)
  const unsafe = classifyTransportError(failure({reason: 'REFERENCE_UPDATE_PENDING', result_through: 'secret', market_through: '2026-10-30T07:00:00Z'}))
  assert.equal(unsafe.referenceStatus, null)
  assert.doesNotMatch(newowErrorDisplay(unsafe.message)!, /secret/)
})

test('source conflict and missing history are not mislabeled as updating', () => {
  for (const code of ['NOT_BUILT', 'SOURCE_IDENTITY_UNVERIFIED', 'STALE_INVALID']) {
    const error = classifyTransportError({response:{status:503,data:{detail:{code}}}})
    assert.equal(error.code, code)
    assert.doesNotMatch(newowErrorDisplay(error.message)!, /参考结果更新中|服务暂不可用/)
  }
  const error = classifyTransportError({response:{status:503,data:{detail:{code:'untrusted'}}}})
  assert.equal(error.code, 'NEWOW_API_UNAVAILABLE')
})
