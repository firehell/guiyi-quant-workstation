import assert from 'node:assert/strict'
import test from 'node:test'
import { createMessageQueryScheduler } from '../src/utils/messageQueryScheduler.ts'
import { useUnifiedMessages } from '../src/composables/useUnifiedMessages.ts'
import type { UnifiedMessagePage, UnifiedMessageQuery } from '../src/api/marketMessages.ts'
import { normalizeAlertHistoryResponse } from '../src/utils/alertHistory.ts'
const query: UnifiedMessageQuery = { startDay: '2026-10-01', endDay: '2026-10-15', symbol: '', ruleCode: null, strategy: '', source: 'all', frequency: '', search: '' }
const event = (id: number) => ({ id, rule_code: 'htdy_original_15m', symbol: 'ag', contract: 'AG2612', trading_day: '2026-10-15', frequency: '15m', bar_end: '2026-10-15T02:45:00Z', result_codes: ['buy'], detected_at: '2026-10-15T02:45:01Z', notification_attempted_at: null })
function page(ids: number[], cursor: string | null = null): UnifiedMessagePage {
  return { items: ids.map(id => ({ source: 'alert', id: String(id), symbol: 'ag', bar_end: '2026-10-15T02:45:00Z', event: event(id) } as UnifiedMessagePage['items'][number])), next_cursor: cursor, available_count: 100, coverage: 'complete', sources: { alert: { status: 'ready', truncated: false, limit: 5000 } }, snapshot: { cutoff: '2026-10-15T05:00:00Z', alert_max_id: 100 } }
}

test('message retention stops at 300 without pretending the source cursor ended', async () => {
  let calls = 0
  const messages = useUnifiedMessages(async () => {
    const start = calls++ * 20
    return page(Array.from({ length: 20 }, (_, index) => start + index), `cursor-${calls}`)
  })
  await messages.load(query)
  for (let index = 0; index < 20; index++) await messages.loadMore()
  assert.equal(calls, 15)
  assert.equal(messages.page.value?.items.length, 300)
  assert.equal(messages.retentionCapped.value, true)
  assert.equal(messages.page.value?.next_cursor, 'cursor-15')
})

test('an oversized message cannot exceed the bounded retained byte budget', async () => {
  const source = page([1], 'more')
  ;(source.items[0]!.event as any).reason = 'x'.repeat(3 * 1024 * 1024)
  const messages = useUnifiedMessages(async () => source)
  await messages.load(query)
  assert.equal(messages.retentionCapped.value, true)
  assert.equal(messages.page.value?.items.length, 0)
})
test('authoritative alert normalizer retains bounded cursors and no delivery claim', () => {
  const value = normalizeAlertHistoryResponse({ status: 'ready', start_day: '2026-10-01', end_day: '2026-10-15', symbol: null, rule_code: null, items: [event(1)], next_before: 'opaque' })
  assert.equal(value.next_before, 'opaque'); assert.equal('delivered' in value.items[0], false)
  assert.throws(() => normalizeAlertHistoryResponse({ ...value, next_before: '' }))
})
test('query changes abort and isolate old first-page responses', async () => {
  const pending: Array<{ signal: AbortSignal; resolve: (value: UnifiedMessagePage) => void }> = []
  const messages = useUnifiedMessages((_query, signal) => new Promise(resolve => pending.push({ signal, resolve })))
  const old = messages.load(query); const next = messages.load({ ...query, symbol: 'jm' })
  assert.equal(pending[0].signal.aborted, true)
  pending[1].resolve(page([2])); await next; pending[0].resolve(page([1])); await old
  assert.deepEqual(messages.page.value?.items.map(item => item.id), ['2'])
})
test('pagination single-flights and deduplicates by source and ID', async () => {
  const calls: Array<string | undefined> = []
  const messages = useUnifiedMessages(async (_query, _signal, cursor) => { calls.push(cursor); return cursor ? page([1, 2]) : page([1], 'two') })
  await messages.load(query); await Promise.all([messages.loadMore(), messages.loadMore()])
  assert.deepEqual(calls, [undefined, 'two']); assert.deepEqual(messages.page.value?.items.map(item => item.id), ['1', '2'])
})
for (const first of ['more', 'refresh']) test(`refresh isolates pending pagination when ${first} resolves first`, async () => {
  let more!: (value: UnifiedMessagePage) => void; let refresh!: (value: UnifiedMessagePage) => void
  let initial = true
  const messages = useUnifiedMessages((_query, _signal, cursor) => {
    if (initial) { initial = false; return Promise.resolve(page([3, 2], 'older')) }
    return new Promise(resolve => { if (cursor) more = resolve; else refresh = resolve })
  })
  await messages.load(query); const old = messages.loadMore(); const next = messages.load(query, true)
  await messages.loadMore() // must not read cached cursor during refresh
  if (first === 'more') { more(page([1])); await old; refresh(page([4])); await next } else { refresh(page([4])); await next; more(page([1])); await old }
  assert.deepEqual(messages.page.value?.items.map(item => item.id), ['4']); assert.equal(messages.loadingMore.value, false)
})
test('reentry restores fresh cached pages without any request', async () => {
  let calls = 0
  const fetcher = async (_query: UnifiedMessageQuery, _signal: AbortSignal, cursor?: string) => { calls++; return cursor ? page([2]) : page([1], 'two') }
  const first = useUnifiedMessages(fetcher, 'cache-test'); await first.load(query); await first.loadMore(); first.dispose()
  const restoredQuery = Object.fromEntries(Object.entries(query).reverse()) as unknown as UnifiedMessageQuery
  const second = useUnifiedMessages(fetcher, 'cache-test'); await second.load(restoredQuery)
  assert.equal(calls, 2); assert.deepEqual(second.page.value?.items.map(item => item.id), ['1', '2'])
  await second.load(query, true); assert.equal(calls, 3); assert.deepEqual(second.page.value?.items.map(item => item.id), ['1'])
})
test('stale snapshots preserve visible facts and disable further pagination', async () => {
  let calls = 0
  const messages = useUnifiedMessages(async (_query, _signal, cursor) => { calls++; if (cursor) throw { response: { status: 409 } }; return page([1], 'two') })
  await messages.load(query); await messages.loadMore(); await messages.loadMore()
  assert.equal(messages.error.value, 'stale'); assert.equal(calls, 2); assert.equal(messages.page.value?.items.length, 1)
})
test('failed refresh retains accepted snapshot and allows its cursor safely', async () => {
  let first = true
  const messages = useUnifiedMessages(async (_query, _signal, cursor) => { if (cursor) return page([2]); if (first) { first = false; return page([1], 'two') }; throw Error('offline') })
  await messages.load(query); await messages.load(query, true)
  assert.equal(messages.error.value, 'failed'); assert.deepEqual(messages.page.value?.items.map(item => item.id), ['1'])
  await messages.loadMore(); assert.deepEqual(messages.page.value?.items.map(item => item.id), ['1', '2'])
})

test('dispose synchronously releases all loading state and ignores pending responses', async () => {
  let resolve!: (value: UnifiedMessagePage) => void
  const messages = useUnifiedMessages(() => new Promise(done => { resolve = done }))
  const pending = messages.load(query)
  assert.equal(messages.loading.value, true)
  messages.dispose()
  assert.equal(messages.loading.value, false)
  assert.equal(messages.loadingMore.value, false)
  resolve(page([1])); await pending
  assert.equal(messages.page.value, null)
})

test('stale cached messages remain labeled as refreshing and failed proof retains old snapshot', async t => {
  let now = 1000; t.mock.method(Date, 'now', () => now)
  const first = useUnifiedMessages(async () => page([1]), 'proof-cache')
  await first.load(query); first.dispose(); now += 30_000
  let reject!: (error: Error) => void
  const next = useUnifiedMessages(() => new Promise((_resolve, failed) => { reject = failed }), 'proof-cache')
  const pending = next.load(query)
  assert.equal(next.loading.value, true)
  assert.deepEqual(next.page.value?.items.map(item => item.id), ['1'])
  reject(Error('offline')); await pending
  assert.equal(next.error.value, 'failed')
  assert.deepEqual(next.page.value?.items.map(item => item.id), ['1'])
})

test('same full dataset hash preserves rows and rebinds cursor to the new snapshot', async t => {
  let now = 1000; t.mock.method(Date, 'now', () => now)
  let calls = 0
  const fetcher = async (_q: UnifiedMessageQuery, _s: AbortSignal, cursor?: string, resumeCount?: number) => {
    calls++
    if (resumeCount !== undefined) assert.equal(resumeCount, 2)
    return { ...page(cursor ? [2] : [1], cursor ? 'third' : 'second'), ...(resumeCount !== undefined ? { resume_cursor: 'rebound', snapshot: { cutoff: '2026-10-15T05:01:00Z', alert_max_id: 100 } } : {}), dataset_hash: 'a'.repeat(64) }
  }
  const first = useUnifiedMessages(fetcher, 'digest-cache'); await first.load(query); await first.loadMore(); first.dispose(); now += 30_000
  const restored = useUnifiedMessages(fetcher, 'digest-cache'); await restored.load(query)
  assert.equal(calls, 3)
  assert.deepEqual(restored.page.value?.items.map(item => item.id), ['1','2'])
  assert.equal(restored.page.value?.next_cursor, 'rebound')
  assert.equal(restored.page.value?.snapshot.cutoff, '2026-10-15T05:01:00Z')
})

test('pagination refuses a changed dataset or snapshot without mixing records', async () => {
  const messages = useUnifiedMessages(async (_q, _s, cursor) => ({...page(cursor ? [2] : [1], cursor ? null : 'next'), dataset_hash: (cursor ? 'b' : 'a').repeat(64)}))
  await messages.load(query); await messages.loadMore()
  assert.equal(messages.error.value, 'stale')
  assert.deepEqual(messages.page.value?.items.map(item => item.id), ['1'])
})


test('load more does not extend the 30 second first-page freshness', async t => {
  let now = 1000; t.mock.method(Date, 'now', () => now)
  let calls = 0
  const messages = useUnifiedMessages(async (_q, _s, cursor) => { calls++; return page(cursor ? [2] : [1], cursor ? null : 'next') }, 'fresh-boundary')
  await messages.load(query)
  now += 29_999; await messages.loadMore(); await messages.load(query)
  assert.equal(calls, 2)
  now++; await messages.load(query)
  assert.equal(calls, 3)
})

test('expired five minute cache fetches and accepts a fresh first page', async t => {
  let now = 1000; t.mock.method(Date, 'now', () => now)
  let calls = 0
  const fetcher = async () => page([++calls])
  const first = useUnifiedMessages(fetcher, 'expired-cache'); await first.load(query); first.dispose()
  now += 300_000
  const next = useUnifiedMessages(fetcher, 'expired-cache'); await next.load(query)
  assert.equal(calls, 2); assert.deepEqual(next.page.value?.items.map(row => row.id), ['2'])
  assert.equal(next.pendingUpdate.value, null)
})

test('changed background result waits for explicit adoption and retains the old list', async t => {
  let now = 1000; t.mock.method(Date, 'now', () => now)
  let calls = 0
  const messages = useUnifiedMessages(async () => ({ ...page([++calls]), dataset_hash: String(calls).repeat(64) }), 'pending-cache')
  await messages.load(query); now += 30_000; await messages.load(query)
  assert.deepEqual(messages.page.value?.items.map(row => row.id), ['1'])
  assert.deepEqual(messages.pendingUpdate.value?.page.items.map(row => row.id), ['2'])
  messages.applyUpdate()
  assert.deepEqual(messages.page.value?.items.map(row => row.id), ['2']); assert.equal(messages.pendingUpdate.value, null)
  await messages.load(query); assert.equal(calls, 2)
})

test('fresh type cache isolates queries and pending update survives switching back', async t => {
  let now = 1000; t.mock.method(Date, 'now', () => now)
  let calls = 0
  const messages = useUnifiedMessages(async q => page([q.symbol === 'jm' ? 9 : ++calls]), 'type-cache')
  await messages.load(query); now += 30_000; await messages.load(query)
  await messages.load({ ...query, symbol: 'jm' }); await messages.load(query)
  assert.equal(calls, 2)
  assert.deepEqual(messages.page.value?.items.map(row => row.id), ['1'])
  assert.deepEqual(messages.pendingUpdate.value?.page.items.map(row => row.id), ['2'])
})

test('search coalesces typing for 350ms and Enter/filter submit immediately', t => {
  t.mock.timers.enable({ apis: ['setTimeout'] })
  let calls = 0
  const scheduler = createMessageQueryScheduler(() => calls++)
  scheduler.schedule(); t.mock.timers.tick(200); scheduler.schedule(); t.mock.timers.tick(349)
  assert.equal(calls, 0); t.mock.timers.tick(1); assert.equal(calls, 1)
  scheduler.schedule(); scheduler.schedule(true); assert.equal(calls, 2)
  t.mock.timers.tick(350); assert.equal(calls, 2)
  scheduler.schedule(); scheduler.cancel(); t.mock.timers.tick(350); assert.equal(calls, 2)
})


test('failed forced refresh preserves shared cache across type changes', async () => {
  let calls = 0
  const fetcher = async () => { calls++; if (calls === 2) throw Error('offline'); return page([1]) }
  const messages = useUnifiedMessages(fetcher, 'force-failure-shared')
  await messages.load(query)
  await messages.load(query, true)
  assert.equal(messages.error.value, 'failed')
  const returned = useUnifiedMessages(fetcher, 'force-failure-shared')
  await returned.load(query)
  assert.equal(calls, 2)
  assert.deepEqual(returned.page.value?.items.map(item => item.id), ['1'])
})
