import assert from 'node:assert/strict'
import test from 'node:test'
import { useReferenceTrading, type ReferenceClient } from '../src/composables/useReferenceTrading.ts'

const window = { since: '2026-09-01', through: '2026-09-23' }
const identity = { strategy: 'subing_reference', product: 'RB', frequency: '1d' }
const stream = { stream_id: 'reference-stream:fixture', readable: true, active_revision_id: 'rev', latest_seq: 2 }
const first = { items: [{ reference_trade_id: 'one', status: 'OPEN', entry_bar_end: '2026-09-01T00:00:00Z' }], snapshot: 'snapshot-1', next_cursor: 'cursor-1', revision_id: 'rev', seq: 2, window, cutoff: null, status: 'READY' }

function client(overrides: Partial<ReferenceClient> = {}): ReferenceClient {
  return {
    streams: async () => [stream] as never,
    trades: async () => first as never,
    summary: async () => ({ snapshot: 'snapshot-1', closed_count: 0 }) as never,
    points: async () => ({ items: [], snapshot: 'snapshot-1', next_cursor: null }) as never,
    ...overrides,
  }
}

test('refresh binds trades, summary and points to one snapshot', async () => {
  const snapshots: string[] = []
  const state = useReferenceTrading(client({
    summary: async (_id, _window, snapshot) => { snapshots.push(snapshot); return { snapshot } as never },
    points: async (_id, _kind, _window, snapshot) => { snapshots.push(snapshot); return { snapshot, items: [], next_cursor: null } as never },
  }))
  await state.refresh(identity, window)
  assert.deepEqual(snapshots, ['snapshot-1', 'snapshot-1', 'snapshot-1'])
  assert.equal(state.page.value?.items.length, 1)
  assert.equal(state.summary.value?.snapshot, 'snapshot-1')
})

test('load more uses pinned snapshot and clears pages on conflict', async () => {
  let pages = 0
  const state = useReferenceTrading(client({
    trades: async (_id, _window, options) => {
      pages += 1
      if (pages === 1) return first as never
      assert.equal(options.snapshot, 'snapshot-1')
      assert.equal(options.cursor, 'cursor-1')
      return { ...first, snapshot: 'snapshot-2', items: [] } as never
    },
  }))
  await state.refresh(identity, window)
  await state.loadMore()
  assert.equal(state.page.value, null)
  assert.match(state.error.value ?? '', /刷新/)
})

test('late response cannot overwrite selected identity', async () => {
  let release!: (value: unknown) => void
  const state = useReferenceTrading(client({
    streams: (_identity) => _identity.product === 'RB'
      ? new Promise(resolve => { release = resolve }) as never
      : Promise.resolve([stream]) as never,
  }))
  const stale = state.refresh(identity, window)
  await state.refresh({ ...identity, product: 'JM' }, window)
  release([stream])
  await stale
  assert.equal(state.page.value?.snapshot, 'snapshot-1')
})

test('presentation points keep the same snapshot across pages', async () => {
  const state = useReferenceTrading(client({
    points: async (_id, kind, _window, snapshot, options) => {
      assert.equal(snapshot, 'snapshot-1')
      if (kind === 'indicators') return { snapshot, items: [], next_cursor: null } as never
      return options.cursor
        ? { snapshot, items: [{ kind: 'signal', trading_day: '2026-09-02', value: {} }], next_cursor: null } as never
        : { snapshot, items: [{ kind: 'signal', trading_day: '2026-09-01', value: {} }], next_cursor: 'point-2' } as never
    },
  }))
  await state.refresh(identity, window)
  assert.equal(state.signals.value.length, 2)
  assert.equal(state.error.value, null)
})
