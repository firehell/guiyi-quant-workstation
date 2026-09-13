import assert from 'node:assert/strict'
import test from 'node:test'
import { useMarketMessages } from '../src/composables/useMarketMessages.ts'
import { normalizeAlertHistoryResponse } from '../src/utils/alertHistory.ts'

const event = (id: number, rule = 'htdy_original_15m') => ({
  id, rule_code: rule, symbol: 'ag', contract: 'AG2612', trading_day: '2026-09-13', frequency: '15m',
  bar_end: `2026-09-13T02:4${id}:00Z`, result_codes: ['buy'], detected_at: `2026-09-13T02:45:0${id}Z`, notification_attempted_at: null,
})

test('normalizes a bounded history page without inventing a total or delivery status', () => {
  const value = normalizeAlertHistoryResponse({ status: 'ready', start_day: '2026-09-07', end_day: '2026-09-13', symbol: null, rule_code: null, items: [event(1)], next_before: 'opaque' })
  assert.equal(value.items[0].id, 1)
  assert.equal(value.next_before, 'opaque')
  assert.equal('total' in value, false)
  assert.equal('delivered' in value.items[0], false)
})

test('rejects malformed history filters and cursors', () => {
  assert.throws(() => normalizeAlertHistoryResponse({ status: 'ready', start_day: '2026-09-14', end_day: '2026-09-13', symbol: null, rule_code: null, items: [], next_before: null }))
  assert.throws(() => normalizeAlertHistoryResponse({ status: 'ready', start_day: '2026-09-07', end_day: '2026-09-13', symbol: null, rule_code: null, items: [], next_before: '' }))
})

test('query changes abort and prevent an old message page from overwriting the new filter', async () => {
  const pending: Array<{ signal: AbortSignal; resolve: (value: ReturnType<typeof normalizeAlertHistoryResponse>) => void }> = []
  const messages = useMarketMessages({ fetchHistory: (_query, signal) => new Promise((resolve) => pending.push({ signal, resolve })) })
  const oldLoad = messages.load({ startDay: '2026-09-07', endDay: '2026-09-13', symbol: '', ruleCode: null })
  const newLoad = messages.load({ startDay: '2026-09-07', endDay: '2026-09-13', symbol: 'jm', ruleCode: null })
  assert.equal(pending[0].signal.aborted, true)
  pending[1].resolve(normalizeAlertHistoryResponse({ status: 'ready', start_day: '2026-09-07', end_day: '2026-09-13', symbol: 'jm', rule_code: null, items: [{ ...event(2), symbol: 'jm', contract: 'JM2609' }], next_before: null }))
  await newLoad
  pending[0].resolve(normalizeAlertHistoryResponse({ status: 'ready', start_day: '2026-09-07', end_day: '2026-09-13', symbol: null, rule_code: null, items: [event(1)], next_before: null }))
  await oldLoad
  assert.deepEqual(messages.items.value.map((item) => item.id), [2])
})

test('loads cursor pages once and appends immutable event identities', async () => {
  const calls: Array<string | null> = []
  const messages = useMarketMessages({ fetchHistory: async (query) => {
    calls.push(query.before ?? null)
    return normalizeAlertHistoryResponse({ status: 'ready', start_day: query.startDay, end_day: query.endDay, symbol: null, rule_code: null, items: [event(query.before ? 2 : 1)], next_before: query.before ? null : 'page-2' })
  } })
  const query = { startDay: '2026-09-07', endDay: '2026-09-13', symbol: '', ruleCode: null } as const
  await messages.load(query)
  await Promise.all([messages.loadMore(), messages.loadMore()])
  assert.deepEqual(calls, [null, 'page-2'])
  assert.deepEqual(messages.items.value.map((item) => item.id), [1, 2])
})

test('restores successful pages, cursor, and scroll by query before a fresh reentry fetch', async () => {
  let now = 1_000
  const calls: Array<string | null> = []
  const fetchHistory = async (query: { before?: string | null }) => {
    calls.push(query.before ?? null)
    if (query.before === 'page-2') return page([event(2)], 'page-3')
    if (query.before === 'page-3') return page([event(3)], null)
    return page([event(1)], 'page-2')
  }
  const query = { startDay: '2026-09-07', endDay: '2026-09-13', symbol: '', ruleCode: null } as const
  const first = useMarketMessages({ fetchHistory, cacheKey: 'messages-reentry', now: () => now })
  await first.load(query)
  await first.loadMore()
  first.rememberScrollTop(640)
  first.dispose()

  const second = useMarketMessages({ fetchHistory, cacheKey: 'messages-reentry', now: () => now })
  const reentry = second.load(query)
  assert.deepEqual(second.items.value.map((item) => item.id), [1, 2])
  assert.equal(second.nextBefore.value, 'page-3')
  assert.equal(second.restoreScrollTop(), 640)
  await reentry
  assert.deepEqual(calls, [null, 'page-2'])
  await second.loadMore()
  assert.deepEqual(second.items.value.map((item) => item.id), [1, 2, 3])

  now += 5 * 60_000 + 1
  let resolveRefresh!: (value: ReturnType<typeof page>) => void
  const expired = useMarketMessages({
    cacheKey: 'messages-reentry',
    now: () => now,
    fetchHistory: () => new Promise((resolve) => { resolveRefresh = resolve }),
  })
  const background = expired.load(query)
  assert.deepEqual(expired.items.value.map((item) => item.id), [1, 2, 3])
  assert.equal(expired.restoreScrollTop(), 640)
  resolveRefresh(page([event(4)], null))
  await background
  assert.deepEqual(expired.items.value.map((item) => item.id), [4])
})

test('keys cached pages by query and lets manual refresh replace a fresh hit', async () => {
  let nextId = 0
  const calls: string[] = []
  const messages = useMarketMessages({
    cacheKey: 'messages-query-and-force',
    fetchHistory: async (query) => {
      calls.push(query.symbol)
      return page([{ ...event(++nextId), symbol: query.symbol || 'ag' }], null)
    },
  })
  const all = { startDay: '2026-09-07', endDay: '2026-09-13', symbol: '', ruleCode: null } as const
  const jm = { ...all, symbol: 'jm' }
  await messages.load(all)
  await messages.load(all)
  await messages.load(jm)
  await messages.load(all)
  assert.deepEqual(calls, ['', 'jm'])
  assert.equal(messages.items.value[0].id, 1)
  await messages.load(all, { force: true })
  assert.deepEqual(calls, ['', 'jm', ''])
  assert.equal(messages.items.value[0].id, 3)
})

for (const refreshKind of ['expired', 'force'] as const) {
  test(`${refreshKind} refresh blocks the cached cursor until its first page is accepted`, async () => {
    let now = 1_000
    const query = { startDay: '2026-09-07', endDay: '2026-09-13', symbol: '', ruleCode: null } as const
    const cacheKey = `messages-${refreshKind}-guard`
    const seed = useMarketMessages({
      cacheKey,
      now: () => now,
      fetchHistory: async () => page([event(3), event(2)], 'page-3'),
    })
    await seed.load(query)
    seed.dispose()
    if (refreshKind === 'expired') now += 5 * 60_000 + 1

    let resolveRefresh!: (value: ReturnType<typeof page>) => void
    const calls: Array<string | null> = []
    const messages = useMarketMessages({
      cacheKey,
      now: () => now,
      fetchHistory: (request) => {
        calls.push(request.before ?? null)
        return new Promise((resolve) => { resolveRefresh = resolve })
      },
    })
    const refresh = messages.load(query, { force: refreshKind === 'force' })
    assert.equal(messages.refreshing.value, true)
    assert.deepEqual(messages.items.value.map((item) => item.id), [3, 2])
    assert.equal(messages.nextBefore.value, 'page-3')
    await messages.loadMore()
    assert.deepEqual(calls, [null])

    resolveRefresh(page([event(4)], 'new-page'))
    await refresh
    assert.equal(messages.refreshing.value, false)
    assert.deepEqual(messages.items.value.map((item) => item.id), [4])
    assert.equal(messages.nextBefore.value, 'new-page')
  })
}

for (const firstToFinish of ['old-more', 'refresh'] as const) {
  test(`an existing page cannot pollute a replacement refresh when ${firstToFinish} finishes first`, async () => {
    const query = { startDay: '2026-09-07', endDay: '2026-09-13', symbol: '', ruleCode: null } as const
    let resolveMore!: (value: ReturnType<typeof page>) => void
    let resolveRefresh!: (value: ReturnType<typeof page>) => void
    const signals: AbortSignal[] = []
    let firstPage = true
    const messages = useMarketMessages({
      cacheKey: `messages-completion-${firstToFinish}`,
      fetchHistory: (request, signal) => {
        signals.push(signal)
        if (firstPage) {
          firstPage = false
          return Promise.resolve(page([event(3), event(2)], 'page-3'))
        }
        if (request.before === 'page-3') return new Promise((resolve) => { resolveMore = resolve })
        return new Promise((resolve) => { resolveRefresh = resolve })
      },
    })
    await messages.load(query)
    const oldMore = messages.loadMore()
    const refresh = messages.load(query, { force: true })
    assert.equal(signals[1].aborted, true)
    assert.equal(messages.refreshing.value, true)

    if (firstToFinish === 'old-more') {
      resolveMore(page([event(1)], null))
      await oldMore
      assert.deepEqual(messages.items.value.map((item) => item.id), [3, 2])
      resolveRefresh(page([event(4)], 'new-page'))
      await refresh
    } else {
      resolveRefresh(page([event(4)], 'new-page'))
      await refresh
      resolveMore(page([event(1)], null))
      await oldMore
    }
    assert.equal(messages.refreshing.value, false)
    assert.deepEqual(messages.items.value.map((item) => item.id), [4])
    assert.equal(messages.nextBefore.value, 'new-page')
  })
}

test('a failed refresh releases the preserved complete cache for its old cursor', async () => {
  let now = 1_000
  const query = { startDay: '2026-09-07', endDay: '2026-09-13', symbol: '', ruleCode: null } as const
  const cacheKey = 'messages-refresh-failure'
  const seed = useMarketMessages({
    cacheKey,
    now: () => now,
    fetchHistory: async () => page([event(3), event(2)], 'page-3'),
  })
  await seed.load(query)
  seed.dispose()
  now += 5 * 60_000 + 1

  let rejectRefresh!: (reason: Error) => void
  const calls: Array<string | null> = []
  const messages = useMarketMessages({
    cacheKey,
    now: () => now,
    fetchHistory: (request) => {
      calls.push(request.before ?? null)
      if (request.before === 'page-3') return Promise.resolve(page([event(1)], null))
      return new Promise((_resolve, reject) => { rejectRefresh = reject })
    },
  })
  const refresh = messages.load(query)
  await messages.loadMore()
  assert.deepEqual(calls, [null])
  rejectRefresh(new Error('refresh failed'))
  await refresh
  assert.equal(messages.refreshing.value, false)
  assert.deepEqual(messages.items.value.map((item) => item.id), [3, 2])
  assert.equal(messages.nextBefore.value, 'page-3')

  await messages.loadMore()
  assert.deepEqual(calls, [null, 'page-3'])
  assert.deepEqual(messages.items.value.map((item) => item.id), [3, 2, 1])
  assert.equal(messages.nextBefore.value, null)
})

for (const outcome of ['resolve', 'reject'] as const) {
  test(`query replacement releases pagination when the old page later ${outcome}s`, async () => {
    let settleOld!: (value?: ReturnType<typeof normalizeAlertHistoryResponse>) => void
    const calls: Array<{ symbol: string; before: string | null }> = []
    const messages = useMarketMessages({ fetchHistory: async (query) => {
      calls.push({ symbol: query.symbol, before: query.before ?? null })
      if (!query.symbol && !query.before) return page([event(1)], 'old-page')
      if (!query.symbol && query.before === 'old-page') {
        return new Promise((resolve, reject) => {
          settleOld = outcome === 'resolve' ? (value) => resolve(value!) : () => reject(new Error('old page failed'))
        })
      }
      if (query.symbol === 'jm' && !query.before) return page([{ ...event(3), symbol: 'jm', contract: 'JM2609' }], 'new-page')
      if (query.symbol === 'jm' && query.before === 'new-page') return page([{ ...event(4), symbol: 'jm', contract: 'JM2609' }], null)
      throw new Error('unexpected query')
    } })
    await messages.load({ startDay: '2026-09-07', endDay: '2026-09-13', symbol: '', ruleCode: null })
    const oldMore = messages.loadMore()
    await messages.load({ startDay: '2026-09-07', endDay: '2026-09-13', symbol: 'jm', ruleCode: null })
    assert.equal(messages.loadingMore.value, false)
    await messages.loadMore()
    assert.deepEqual(calls.at(-1), { symbol: 'jm', before: 'new-page' })
    settleOld(page([event(2)], null))
    await oldMore
    assert.deepEqual(messages.items.value.map((item) => item.id), [3, 4])
    assert.equal(messages.loadingMore.value, false)
    assert.equal(messages.nextBefore.value, null)
  })
}

function page(items: ReturnType<typeof event>[], nextBefore: string | null) {
  return normalizeAlertHistoryResponse({ status: 'ready', start_day: '2026-09-07', end_day: '2026-09-13', symbol: null, rule_code: null, items, next_before: nextBefore })
}
