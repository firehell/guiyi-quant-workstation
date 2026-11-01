import test from 'node:test'
import assert from 'node:assert/strict'
import { useForwardReferencePanel } from '../src/composables/useForwardReferencePanel.ts'
const window = { since: '2026-10-01', through: '2026-10-23' }
const identity = { strategy: 'htdy', product: 'JM', frequency: '15m' }
const stream = { stream_id: 'test-stream', active_revision_id: 'r', latest_seq: 1, activation_generation: 1, readable: true, recording_mode: 'forward_observation' }
const first = { snapshot: 'exact', revision_id: 'r', seq: 1, items: [{ reference_trade_id: 'one' }], next_cursor: 'more', window, stream }
function client(overrides = {}) {
  return { streams: async () => [stream], panel: async () => ({ version: 'forward_reference_panel_v1', page: first, summary: { snapshot: 'exact' }, curve: [] }), trades: async () => ({ ...first, items: [{ reference_trade_id: 'two' }], next_cursor: null }), ...overrides } as never
}
test('panel requests only forward streams, no indicator/signal reads, and lazy paging', async () => {
  let pages = 0
  const state = useForwardReferencePanel(client({
    streams: async (value: unknown) => { assert.deepEqual(value, { ...identity, mode: 'forward_observation' }); return [stream] },
    trades: async (_id: string, _window: unknown, options: { snapshot: string; cursor: string }) => { pages++; assert.equal(options.snapshot, 'exact'); assert.equal(options.cursor, 'more'); return { ...first, items: [{ reference_trade_id: 'two' }], next_cursor: null } },
  }))
  await state.refresh(identity, window, true)
  assert.equal(state.error.value, null); assert.equal(pages, 0)
  await state.loadMore()
  assert.equal(state.rows.value.length, 2); assert.equal(pages, 1)
  state.dispose()
})
test('empty stream and disabled stream are explicit and never fall back to replay', async () => {
  for (const streams of [[], [{ ...stream, readable: false }]]) {
    let panels = 0
    const state = useForwardReferencePanel(client({ streams: async () => streams, panel: async () => { panels++; throw Error() } }))
    await state.refresh(identity, window)
    assert.equal(state.data.value, null); assert.equal(panels, 0); assert.ok(state.error.value)
    state.dispose()
  }
})
test('identity changes cancel late results, conflicting pages preserve exact existing records', async () => {
  let release!: (value: unknown) => void
  const state = useForwardReferencePanel(client({ streams: (id: { product: string }) => id.product === 'RB' ? new Promise(resolve => { release = resolve }) : Promise.resolve([stream]), trades: async () => ({ ...first, snapshot: 'changed', items: [] }) }))
  const old = state.refresh({ ...identity, product: 'RB' }, window)
  await state.refresh(identity, window, true)
  release([stream]); await old
  await state.loadMore()
  assert.equal(state.rows.value[0]?.reference_trade_id, 'one')
  assert.match(state.moreError.value ?? '', /快照/)
  state.dispose()
})
test('invalid HTTP success is not cached and next refresh retries transport', async () => {
  let calls = 0
  const state = useForwardReferencePanel(client({ panel: async () => {
    calls++
    return { version: 'forward_reference_panel_v1', page: first, summary: { snapshot: calls === 1 ? 'wrong' : 'exact' }, curve: [] }
  } }))
  const unique = { ...identity, product: 'SI' }
  await state.refresh(unique, window, true)
  assert.ok(state.error.value)
  await state.refresh(unique, window)
  assert.equal(calls, 2); assert.equal(state.error.value, null)
  state.dispose()
})


test('a late panel cannot overwrite a newly accepted product or window', async () => {
  let release!: (value: unknown) => void
  let started!: () => void
  const pending = new Promise<void>(resolve => { started = resolve })
  const newer = {since:'2026-10-02',through:'2026-10-23'}
  const state = useForwardReferencePanel(client({panel: async (_id:string, range:typeof window) => {
    if (range.since === window.since) { started(); return new Promise(resolve => {release = resolve}) }
    return {version:'forward_reference_panel_v1',page:{...first,window:newer,items:[{reference_trade_id:'new-product'}]},summary:{snapshot:'exact'},curve:[]}
  }}))
  const old = state.refresh({...identity, product:'OLD'},window,true)
  await pending
  await state.refresh({...identity,product:'NEW'},newer,true)
  release({version:'forward_reference_panel_v1',page:first,summary:{snapshot:'exact'},curve:[]})
  await old
  assert.equal(state.rows.value[0]?.reference_trade_id,'new-product')
  assert.equal(state.data.value?.page.window.since,newer.since)
  state.dispose()
})
