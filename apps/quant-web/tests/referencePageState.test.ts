import assert from 'node:assert/strict'
import test from 'node:test'
import { createReferencePageState } from '../src/composables/referencePageState.ts'

test('shared reference pages pin identity and cursor and reject replayed records', () => {
  const state = createReferencePageState<{ id: string }>(item => item.id)
  state.first('snapshot-a', [{ id: 'new' }], 'older')
  assert.deepEqual(state.append('snapshot-a', 'older', [{ id: 'old' }], null), [{ id: 'new' }, { id: 'old' }])
  assert.equal(state.cursor, null)
  assert.throws(() => state.append('snapshot-a', 'older', [], null), /SNAPSHOT_CONFLICT/)
  state.first('snapshot-a', [{ id: 'new' }], 'older')
  assert.throws(() => state.append('snapshot-b', 'older', [], null), /SNAPSHOT_CONFLICT/)
  assert.throws(() => state.append('snapshot-a', 'wrong', [], null), /SNAPSHOT_CONFLICT/)
  assert.throws(() => state.append('snapshot-a', 'older', [{ id: 'new' }], null), /SNAPSHOT_CONFLICT/)
})

test('saved Newow pages tolerate identical overlap and stop at the display cap', () => {
  const state = createReferencePageState<{ id: string; value: number }>(item => item.id, 2, true)
  state.first('snapshot-a', [{ id: 'new', value: 1 }], 'older')
  assert.deepEqual(state.append('snapshot-a', 'older', [{ id: 'new', value: 1 }, { id: 'old', value: 2 }], 'next'), [
    { id: 'new', value: 1 }, { id: 'old', value: 2 },
  ])
  assert.equal(state.cursor, null)
  state.first('snapshot-a', [{ id: 'new', value: 1 }], 'older')
  assert.throws(() => state.append('snapshot-a', 'older', [{ id: 'new', value: 3 }], null), /SNAPSHOT_CONFLICT/)
})
