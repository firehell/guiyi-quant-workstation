import assert from 'node:assert/strict'
import test from 'node:test'
import { ref } from 'vue'
import { buildNewowFixtureEnvelopeForTest } from '../e2e/newow-product.helpers.mjs'
import { newowComparisonCompatible } from '../src/utils/newowComparison.ts'
import { useNewowComparison } from '../src/composables/useNewowComparison.ts'
import { NewowProductRequestError } from '../src/api/newowProduct.ts'
function chart(strategy = 'trend') { const raw = buildNewowFixtureEnvelopeForTest('chart', strategy, '1d', false, null, { dualMarket: true }); return { meta: raw.meta, section: 'chart', ...raw.chart } }
test('comparison accepts independent tokens only with equal time, market and calculation segment facts', () => {
  const a = chart(), b = chart('oscillation')
  assert.equal(newowComparisonCompatible(a, b), true)
  for (const mutate of [value => { value.meta.as_of = '2026-09-04T08:00:00.000Z' }, value => { value.value.bars[0].close = '777' }, value => { value.value.bars[0].physical_contract = 'RB2610' }, value => { value.value.bars[0].calculation_segment_id = 'different' }, value => { value.value.bars.shift() }, value => { value.meta.identity.strategy = 'main_rise' }]) {
    const copy = structuredClone(b); mutate(copy); assert.equal(newowComparisonCompatible(a, copy), false)
  }
})
test('disabled comparison performs no request and late unabortable response cannot survive identity replacement', async () => {
  const base = ref(chart()), enabled = ref(false)
  const pending = []
  const comparison = useNewowComparison(base, enabled, (request, signal) => new Promise(resolve => pending.push({ request, signal, resolve })))
  assert.equal(pending.length, 0)
  assert.equal(comparison.referenceSettled.value, false)
  enabled.value = true; assert.equal(pending.length, 1)
  assert.equal(pending[0].request.asOf, base.value.meta.as_of)
  assert.equal(pending[0].request.snapshotToken, undefined)
  enabled.value = false; pending[0].resolve(chart('oscillation'))
  await Promise.resolve(); await Promise.resolve()
  assert.equal(comparison.response.value, null)
  assert.equal(comparison.state.value, 'not_requested')
  assert.equal(pending[0].signal.aborted, true)
  comparison.dispose()
})

test('comparison requests the whole accumulated axis after an older display window was appended', async () => {
  const value = chart()
  value.value.chart_from = '2025-01-01'; value.value.chart_through = '2025-12-31'
  const base = ref(value), enabled = ref(true)
  const requests = []
  const partner = chart('oscillation')
  const comparison = useNewowComparison(base, enabled, async request => { requests.push(request); return partner })
  await Promise.resolve(); await Promise.resolve()
  assert.equal(requests[0].from, '2025-01-01')
  assert.equal(requests[0].through, '2026-08-03')
  assert.equal(comparison.state.value, 'ready')
  comparison.dispose()
})

test('partner reference records retain their token and a late response cannot survive disabling dual mode', async () => {
  const base = ref(chart()), enabled = ref(true), partner = chart('oscillation')
  let resolveReference
  const requests = []
  const comparison = useNewowComparison(base, enabled, async request => {
    requests.push(request)
    return request.section === 'chart' ? partner : new Promise(resolve => { resolveReference = resolve })
  })
  await Promise.resolve(); await Promise.resolve()
  assert.equal(comparison.state.value, 'ready')
  assert.equal(requests[1].section, 'reference')
  assert.equal(requests[1].snapshotToken, partner.meta.snapshot_token)
  enabled.value = false
  resolveReference({ section: 'reference', meta: partner.meta, status: { status: 'ready' }, value: { items: [] } })
  await Promise.resolve(); await Promise.resolve(); await Promise.resolve()
  assert.equal(comparison.reference.value, null)
  assert.equal(comparison.referenceError.value, null)
  comparison.dispose()
})

test('a conflicting partner reference token does not decorate labels or revoke valid chart comparison', async () => {
  const partner = chart('oscillation')
  const comparison = useNewowComparison(ref(chart()), ref(true), async request => request.section === 'chart' ? partner
    : { section: 'reference', meta: { ...partner.meta, snapshot_token: 'different' }, status: { status: 'ready' }, value: { items: [] } })
  for (let i = 0; i < 5; i++) await Promise.resolve()
  assert.equal(comparison.state.value, 'ready')
  assert.equal(comparison.reference.value, null)
  assert.ok(comparison.referenceError.value)
  assert.equal(comparison.referenceSettled.value, true)
  comparison.dispose()
})


async function flushComparison() { for (let i = 0; i < 6; i++) await Promise.resolve() }

test('fusion admission waits for delayed partner reference and opens after success or failure', async () => {
  for (const fails of [false, true]) {
    const partner = chart('oscillation')
    let finish, reject
    const comparison = useNewowComparison(ref(chart()), ref(true), async request => request.section === 'chart' ? partner
      : new Promise((resolve, fail) => { finish = resolve; reject = fail }))
    await flushComparison()
    assert.equal(comparison.state.value, 'ready')
    assert.equal(comparison.referenceSettled.value, false, 'chart readiness cannot start fusion while reference is pending')
    if (fails) reject(new Error('reference transport failed'))
    else finish({ section: 'reference', meta: partner.meta, status: { status: 'ready' }, value: { items: [] } })
    await flushComparison()
    assert.equal(comparison.referenceSettled.value, true)
    assert.equal(Boolean(comparison.referenceError.value), fails)
    comparison.dispose()
  }
})

test('replaced identity aborts partner reference and stale completion cannot admit current fusion', async () => {
  const base = ref(chart()), enabled = ref(true), pending = []
  const comparison = useNewowComparison(base, enabled, async (request, signal) => {
    const partner = chart('oscillation'); partner.meta.identity.product = request.identity.product; partner.meta.identity.frequency = request.identity.frequency
    return request.section === 'chart' ? partner : new Promise(resolve => pending.push({ resolve, signal, partner }))
  })
  await flushComparison()
  assert.equal(comparison.referenceSettled.value, false)
  const replacement = chart(); replacement.meta.identity.product = 'j'; replacement.meta.identity.frequency = '1w'; base.value = replacement
  await flushComparison()
  assert.equal(pending.length, 2)
  assert.equal(pending[0].signal.aborted, true)
  pending[0].resolve({ section: 'reference', meta: pending[0].partner.meta, status: { status: 'ready' }, value: { items: [] } })
  await flushComparison()
  assert.equal(comparison.referenceSettled.value, false)
  assert.equal(comparison.reference.value, null)
  pending[1].resolve({ section: 'reference', meta: pending[1].partner.meta, status: { status: 'ready' }, value: { items: [] } })
  await flushComparison()
  assert.equal(comparison.referenceSettled.value, true)
  assert.equal(comparison.reference.value.meta.identity.product, 'j')
  assert.equal(comparison.reference.value.meta.identity.frequency, '1w')
  enabled.value = false
  assert.equal(comparison.referenceSettled.value, false)
  comparison.dispose()
})

test('terminal comparison failure releases fusion admission without retrying partner requests', async () => {
  let calls = 0
  const comparison = useNewowComparison(ref(chart()), ref(true), async () => { ++calls; throw new Error('chart failed') })
  await flushComparison()
  assert.equal(comparison.state.value, 'unavailable')
  assert.equal(comparison.referenceSettled.value, true)
  assert.equal(calls, 1)
  comparison.dispose()
})


test('comparison conflict and missing chart window settle without starting partner reference', async () => {
  for (const missingWindow of [false, true]) {
    const accepted = chart(), partner = chart('oscillation')
    if (missingWindow) accepted.value.bars = []
    else partner.value.bars[0].close = '777'
    let calls = 0
    const comparison = useNewowComparison(ref(accepted), ref(true), async () => { ++calls; return partner })
    await flushComparison()
    assert.equal(comparison.state.value, missingWindow ? 'unavailable' : 'input_conflict')
    assert.equal(comparison.referenceSettled.value, true)
    assert.equal(calls, missingWindow ? 0 : 1)
    comparison.dispose()
    assert.equal(comparison.referenceSettled.value, false)
  }
})

test('disposal aborts a pending partner reference and its late failure cannot reopen admission', async () => {
  const partner = chart('oscillation')
  let reject, signal
  const comparison = useNewowComparison(ref(chart()), ref(true), async (request, requestSignal) => request.section === 'chart' ? partner
    : new Promise((_resolve, fail) => { reject = fail; signal = requestSignal }))
  await flushComparison()
  comparison.dispose()
  assert.equal(signal.aborted, true)
  assert.equal(comparison.referenceSettled.value, false)
  reject(new Error('late transport failure'))
  await flushComparison()
  assert.equal(comparison.referenceError.value, null)
  assert.equal(comparison.referenceSettled.value, false)
})


test('non-ready and conflicting partner reference responses settle as unavailable without retries', async () => {
  for (const status of ['warming', 'unavailable', 'wrong-token']) {
    const partner = chart('oscillation')
    let finish, calls = 0
    const comparison = useNewowComparison(ref(chart()), ref(true), async request => {
      ++calls
      return request.section === 'chart' ? partner : new Promise(resolve => { finish = resolve })
    })
    await flushComparison()
    assert.equal(comparison.referenceSettled.value, false)
    finish({ section: 'reference', meta: { ...partner.meta, snapshot_token: status === 'wrong-token' ? 'wrong-token' : partner.meta.snapshot_token },
      status: { status: status === 'wrong-token' ? 'ready' : status }, value: { items: [] } })
    await flushComparison()
    assert.equal(comparison.state.value, 'ready')
    assert.equal(comparison.reference.value, null)
    assert.ok(comparison.referenceError.value)
    assert.equal(comparison.referenceSettled.value, true)
    assert.equal(calls, 2)
    comparison.dispose()
  }
})

test('partner reference snapshot conflict rebuilds the same chart window once and binds a fresh reference token', async () => {
  const first = chart('oscillation'), fresh = chart('oscillation')
  first.meta.snapshot_token = 'first-partner-token'; fresh.meta.snapshot_token = 'fresh-partner-token'
  const requests = []
  const comparison = useNewowComparison(ref(chart()), ref(true), async request => {
    requests.push(request)
    if (request.section === 'chart') return requests.filter(item => item.section === 'chart').length === 1 ? first : fresh
    if (request.snapshotToken === first.meta.snapshot_token) throw new NewowProductRequestError('NEWOW_SNAPSHOT_GENERATION_CONFLICT', 'conflict')
    return { section: 'reference', meta: fresh.meta, status: { status: 'ready' }, value: { items: [] } }
  })
  await flushComparison()
  assert.deepEqual(requests.map(item => item.section), ['chart', 'reference', 'chart', 'reference'])
  assert.deepEqual(requests[2], requests[0], 'recovery must use the same chart window and no rejected token')
  assert.equal(requests[3].snapshotToken, fresh.meta.snapshot_token)
  assert.equal(comparison.response.value?.meta.snapshot_token, fresh.meta.snapshot_token)
  assert.equal(comparison.reference.value?.meta.snapshot_token, fresh.meta.snapshot_token)
  assert.equal(comparison.referenceError.value, null)
  comparison.dispose()
})

test('partner conflict recovery stops after a second conflict or a non-conflict error', async () => {
  for (const secondConflict of [true, false]) {
    const requests = []
    const first = chart('oscillation'), fresh = chart('oscillation')
    first.meta.snapshot_token = 'first-partner-token'; fresh.meta.snapshot_token = 'fresh-partner-token'
    const comparison = useNewowComparison(ref(chart()), ref(true), async request => {
      requests.push(request)
      if (request.section === 'chart') return requests.filter(item => item.section === 'chart').length === 1 ? first : fresh
      throw new NewowProductRequestError(secondConflict ? 'NEWOW_SNAPSHOT_GENERATION_CONFLICT' : 'NEWOW_API_UNAVAILABLE', secondConflict ? 'conflict' : 'unavailable')
    })
    await flushComparison()
    assert.deepEqual(requests.map(item => item.section), secondConflict ? ['chart', 'reference', 'chart', 'reference'] : ['chart', 'reference'])
    assert.equal(comparison.reference.value, null)
    assert.ok(comparison.referenceError.value)
    assert.equal(comparison.referenceSettled.value, true)
    comparison.dispose()
  }
})

test('a matching code without conflict classification does not trigger partner recovery', async () => {
  const requests = [], partner = chart('oscillation')
  const comparison = useNewowComparison(ref(chart()), ref(true), async request => {
    requests.push(request)
    if (request.section === 'chart') return partner
    throw new NewowProductRequestError('NEWOW_SNAPSHOT_GENERATION_CONFLICT', 'unavailable')
  })
  await flushComparison()
  assert.deepEqual(requests.map(item => item.section), ['chart', 'reference'])
  assert.ok(comparison.referenceError.value)
  comparison.dispose()
})

test('changed market facts in the rebuilt partner chart fail closed before fresh reference', async () => {
  const first = chart('oscillation'), changed = chart('oscillation'), requests = []
  changed.value.bars[0].close = '777'
  const comparison = useNewowComparison(ref(chart()), ref(true), async request => {
    requests.push(request)
    if (request.section === 'chart') return requests.filter(item => item.section === 'chart').length === 1 ? first : changed
    throw new NewowProductRequestError('NEWOW_SNAPSHOT_GENERATION_CONFLICT', 'conflict')
  })
  await flushComparison()
  assert.deepEqual(requests.map(item => item.section), ['chart', 'reference', 'chart'])
  assert.equal(comparison.state.value, 'input_conflict')
  assert.equal(comparison.response.value, null)
  assert.equal(comparison.reference.value, null)
  assert.equal(comparison.referenceSettled.value, true)
  comparison.dispose()
})

test('disabled comparison drops a late rebuilt chart and never dispatches fresh reference', async () => {
  const enabled = ref(true), first = chart('oscillation'), fresh = chart('oscillation'), requests = []
  fresh.value.bars = fresh.value.bars.slice(0, 1)
  fresh.value.next_before = '2026-08-01T00:00:00Z'
  let finishRebuild
  const comparison = useNewowComparison(ref(chart()), enabled, async request => {
    requests.push(request)
    if (request.section === 'chart') return requests.filter(item => item.section === 'chart').length === 1
      ? first : new Promise(resolve => { finishRebuild = resolve })
    throw new NewowProductRequestError('NEWOW_SNAPSHOT_GENERATION_CONFLICT', 'conflict')
  })
  await flushComparison()
  assert.deepEqual(requests.map(item => item.section), ['chart', 'reference', 'chart'])
  assert.equal(comparison.state.value, 'loading')
  assert.equal(comparison.referenceSettled.value, false)
  enabled.value = false
  finishRebuild(fresh)
  await flushComparison()
  assert.deepEqual(requests.map(item => item.section), ['chart', 'reference', 'chart'])
  assert.equal(comparison.state.value, 'not_requested')
  assert.equal(comparison.response.value, null)
  comparison.dispose()
})

test('abort or base replacement during rejected partner reference cannot dispatch recovery', async () => {
  for (const replaceBase of [false, true]) {
    const base = ref(chart()), enabled = ref(true), requests = []
    let rejectReference
    const comparison = useNewowComparison(base, enabled, async request => {
      requests.push(request)
      return request.section === 'chart' ? chart('oscillation') : new Promise((_resolve, reject) => { rejectReference = reject })
    })
    await flushComparison()
    if (replaceBase) { const replacement = chart(); replacement.meta.identity.product = 'j'; base.value = replacement }
    else enabled.value = false
    rejectReference(new NewowProductRequestError('NEWOW_SNAPSHOT_GENERATION_CONFLICT', 'conflict'))
    await flushComparison()
    assert.equal(requests.filter(item => item.identity.product === 'rb').length, 2)
    assert.equal(comparison.reference.value, null)
    comparison.dispose()
  }
})
