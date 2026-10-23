import assert from 'node:assert/strict'
import { it } from 'node:test'
import { useHtdyHistoricalReference } from '../src/composables/useHtdyHistoricalReference.ts'
import type { HtdyHistoricalResponse } from '../src/types/htdyReference.ts'
function response(token = 'a'): HtdyHistoricalResponse {
  return { schema_version: 'htdy_historical_reference_v1', recording_mode: 'historical_replay', product: 'jm', frequency: '15m', source_token: token, computed_through: '2026-10-23T07:00:00Z', since: '2026-01-01', through: '2026-10-23', trades: [], signals: [], summary: { total: 0, closed: 0, open: 0 }, next_cursor: 'a:50' }
}
it('rejects a changed source when paging and preserves the previous result', async () => {
  let calls = 0
  const reference = useHtdyHistoricalReference(async () => response(++calls === 1 ? 'a' : 'b'))
  reference.reset('jm', '15m'); await reference.read(); await reference.read(true)
  assert.equal(reference.result.value?.source_token, 'a')
  assert.ok(reference.error.value)
  reference.dispose()
})
it('ignores a late response after identity reset', async () => {
  let finish!: (value: HtdyHistoricalResponse) => void
  const reference = useHtdyHistoricalReference(() => new Promise(resolve => { finish = resolve }))
  reference.reset('jm', '15m'); const pending = reference.read()
  reference.reset('rb', '15m'); finish(response()); await pending
  assert.equal(reference.result.value, null)
  assert.equal(reference.loading.value, false)
  reference.dispose()
})
it('does not refetch on missing next cursor', async () => {
  let calls = 0
  const reference = useHtdyHistoricalReference(async () => { calls++; return { ...response(), next_cursor: null } })
  reference.reset('jm', '15m'); await reference.read(); await reference.read(true)
  assert.equal(calls, 1)
  reference.dispose()
})

it('pins pagination to the original window and completed cutoff', async () => {
  const queries: Record<string, unknown>[] = []
  const reference = useHtdyHistoricalReference(async (_symbol, params) => {
    queries.push(params)
    return { ...response(), next_cursor: queries.length === 1 ? 'a:50' : null }
  })
  reference.reset('jm', '15m'); await reference.read(); await reference.read(true)
  assert.equal(queries[1].since, '2026-01-01')
  assert.equal(queries[1].through, '2026-10-23')
  assert.equal(queries[1].as_of, '2026-10-23T07:00:00Z')
  reference.dispose()
})
it('marks a newer completed bar stale without fetching and rejects excessive date windows', async () => {
  let calls = 0
  const reference = useHtdyHistoricalReference(async () => { calls++; return response() })
  reference.reset('jm', '15m'); await reference.read()
  reference.latestBar.value = '2026-10-23T07:15:00Z'
  assert.equal(reference.stale.value, true)
  assert.equal(calls, 1)
  await reference.read(false, { since: '2024-01-01', through: '2026-10-23' })
  assert.equal(calls, 1)
  assert.match(reference.error.value ?? '', /365/)
  assert.equal(reference.result.value?.source_token, 'a')
  reference.dispose()
})
