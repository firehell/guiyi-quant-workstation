import assert from 'node:assert/strict'
import test from 'node:test'
import { getNewowRecordingMatrix } from '../src/api/referenceTrading.ts'
import { recordingStatusLabel, recordingStateLabel, recordingPointLabel, newowRecordingWindow } from '../src/utils/newowRecording.ts'

test('matrix read is explicit forward and validates version rather than inventing records', async () => {
  const response = { version: 'newow_recording_matrix_v1', recording_mode: 'forward_observation', expected_count: 720,
    configured_count: 0, enabled_count: 0, observed_count: 0, items: [] }
  let path = ''
  assert.equal(await getNewowRecordingMatrix({ request: async url => { path = url; return response } }), response)
  assert.equal(path, '/reference-trading/newow/matrix')
  await assert.rejects(getNewowRecordingMatrix({ request: async () => ({ ...response, recording_mode: 'historical_replay' }) }), /REFERENCE_RESPONSE_INVALID/)
})

test('missing and warming states never display a fabricated flat state', () => {
  assert.equal(recordingStateLabel(null), '尚无已记录状态')
  assert.equal(recordingStateLabel({ availability: 'warming', main_state: 'FLAT' }), '预热中')
  assert.equal(recordingStateLabel({ availability: 'ready', main_state: 'FLAT' }), '空仓')
  assert.equal(recordingStatusLabel('not_configured'), '未配置')
  assert.equal(recordingStatusLabel('waiting_first_bar'), '等待首根已完成 K 线')
  assert.equal(recordingStatusLabel('blocked'), '记录阻断')
})

test('recorded state and action descriptions use saved facts and isolate unknown values', () => {
  assert.equal(recordingPointLabel({ kind: 'signal', trading_day: '2026-10-08', formula_versions: [], value: { kind: 'BUILD' } }), '建仓')
  assert.equal(recordingPointLabel({ kind: 'bar_state', trading_day: '2026-10-08', formula_versions: [], value: { version: 'newow_bar_state_v1', main_state: 'HOLD', availability: 'ready' } }), '持有')
  assert.equal(recordingStateLabel({ main_state: 'unexpected', availability: 'ready' }), '未知状态（unexpected）')
})

test('record window uses Shanghai calendar without future dates', () => {
  assert.deepEqual(newowRecordingWindow(new Date('2026-10-07T18:00:00Z')), { since: '2026-07-10', through: '2026-10-08' })
})

test('record detail locks both action and state pages to the same saved snapshot', async () => {
  const { getNewowRecordingRecords } = await import('../src/api/referenceTrading.ts')
  const calls: { url: string; params: Record<string, unknown> }[] = []
  const page = { items: [], snapshot: 'snap', revision_id: 'rev', seq: 1, next_cursor: null,
    window: { since: '2026-10-01', through: '2026-10-08' }, cutoff: null, status: 'ready' }
  const request = async (url: string, { params }: { params: Record<string, unknown> }) => { calls.push({ url, params }); return page }
  await getNewowRecordingRecords('selected-stream', page.window, { request })
  assert.ok(calls[0]?.url.endsWith('/trades'))
  assert.equal(calls[1]?.params.snapshot, 'snap')
  assert.equal(calls[2]?.params.snapshot, 'snap')
  assert.equal(calls[2]?.params.limit, 50)
  await assert.rejects(getNewowRecordingRecords('selected-stream', page.window, {
    request: async url => url.endsWith('/indicators') ? { ...page, snapshot: 'changed' } : page,
  }), /SNAPSHOT_CONFLICT/)
})

test('availability proof is required before displaying a strategy state', () => {
  assert.equal(recordingStateLabel({ main_state: 'FLAT' }), '状态可用性未记录')
  assert.equal(recordingStateLabel({ main_state: 'HOLD', availability: { status: 'warming', reason_code: 'WARM_UP' } }), '预热中')
  assert.equal(recordingStateLabel({ main_state: 'HOLD', availability: { status: 'ready' } }), '持有')
})

test('J and escape hints retain hint semantics without claiming an executed reduction', () => {
  const point = { kind: 'hint', trading_day: '2026-10-08', formula_versions: [], value: { kind: 'J' } }
  assert.equal(recordingPointLabel(point), 'J 风险提示')
  assert.equal(recordingPointLabel({ ...point, value: { kind: 'D1' } }), 'D1 逃顶提示')
})

test('historical stream query uses canonical lower-case Newow product and explicit mode', async () => {
  const { newowRecordingIdentity } = await import('../src/utils/newowRecording.ts')
  assert.deepEqual(newowRecordingIdentity('RB', 'main_rise', '60m', 'historical_replay'), {
    product: 'rb', strategy: 'newow-main-rise', frequency: '60m', mode: 'historical_replay',
  })
})

test('matrix health distinguishes saved READY seed from actual observed records', async () => {
  const { recordingItemStatus } = await import('../src/utils/newowRecording.ts')
  const row = { status: 'READY', stream_id: 'seeded', enabled: true, latest_state: null }
  assert.equal(recordingStatusLabel('NOT_CONFIGURED'), '未配置')
  assert.equal(recordingItemStatus(row), '等待首根已完成 K 线')
  assert.equal(recordingItemStatus({ ...row, enabled: false }), '未启用')
  assert.equal(recordingItemStatus({ ...row, status: 'STALE_INVALID' }), '记录阻断')
})

test('matrix v2 preserves seed evidence separately from natural observation', async () => {
  const row = { product: 'rb', strategy: 'trend', frequency: '60m', stream_id: 'seeded', enabled: true, status: 'READY',
    computed_through: '2026-10-08T07:00:00Z', historical_computed_through: '2026-10-08T07:00:00Z',
    observed_through: null, last_observed_at: null, latest_state: null, latest_state_source: 'historical_seed',
    expected_through: '2026-10-08T07:00:00Z', expected_source: 'canonical_completed', endpoint_status: 'READY', endpoint_reason: null }
  const response = { version: 'newow_recording_matrix_v2', recording_mode: 'forward_observation', expected_count: 12,
    configured_count: 1, enabled_count: 1, observed_count: 0, seeded_count: 1, items: [row] }
  assert.equal(await getNewowRecordingMatrix({ request: async () => response }), response)
  await assert.rejects(getNewowRecordingMatrix({ request: async () => ({ ...response, observed_count: 13 }) }), /REFERENCE_RESPONSE_INVALID/)
  await assert.rejects(getNewowRecordingMatrix({ request: async () => ({ ...response, items: [{ ...row, latest_state_source: 'invented' }] }) }), /REFERENCE_RESPONSE_INVALID/)
})

test('historical warm-up state is never labelled as a natural observation', async () => {
  const { recordingItemStatus } = await import('../src/utils/newowRecording.ts')
  assert.equal(recordingItemStatus({ stream_id: 'warm', enabled: true, status: 'READY',
    latest_state: { main_state: 'HOLD', availability: { status: 'ready' } },
    latest_state_source: 'historical_seed', observed_through: null }), '等待首根已完成 K 线')
})
