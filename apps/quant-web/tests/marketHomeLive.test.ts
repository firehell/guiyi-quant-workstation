import assert from 'node:assert/strict'
import test from 'node:test'
import { useMarketHomeLive } from '../src/composables/useMarketHomeLive.ts'
import { normalizeMarketHomeLiveFrame } from '../src/utils/marketHomeLive.ts'

const quote = (overrides = {}) => ({ symbol: 'ag', physical_contract: 'AG2612', trading_day: '2026-09-13', bar_end: '2026-09-13T02:31:00Z', price: '8123.5', previous_close: '8000', price_change: '0.0154375', source: 'completed_1m', availability: 'live', phase: 'TRADING', reason: null, ...overrides })

test('normalizes Decimal strings and preserves typed unavailable reasons', () => {
  const frame = normalizeMarketHomeLiveFrame({ type: 'snapshot', schema_version: 1, observed_at: '2026-09-13T02:31:01Z', scope: 'operational', items: [quote(), quote({ symbol: 'jm', physical_contract: null, trading_day: null, bar_end: null, price: null, previous_close: null, price_change: null, source: 'none', availability: 'unavailable', phase: 'UNKNOWN', reason: 'NO_COMPLETED_VALUE' })] })
  assert.equal(frame.type, 'snapshot')
  if (frame.type !== 'snapshot') return
  assert.equal(frame.items[0].price, 8123.5)
  assert.equal(frame.items[0].priceChange, 0.0154375)
  assert.equal(frame.items[1].reason, 'NO_COMPLETED_VALUE')
})

test('accepts a complete 60-item snapshot when one unavailable product retains its contract identity', () => {
  const unavailable = quote({ symbol: 'p59', physical_contract: 'P592701', trading_day: null, bar_end: null, price: null, previous_close: null, price_change: null, source: 'none', availability: 'unavailable', phase: 'CLOSED', reason: 'PRICE_UNAVAILABLE' })
  const payload = {
    type: 'snapshot', schema_version: 1, observed_at: '2026-09-13T02:31:01Z', scope: 'operational',
    items: Array.from({ length: 59 }, (_, index) => quote({ symbol: `p${index}`, physical_contract: `P${index}2701` })).concat(unavailable),
  }
  const frame = normalizeMarketHomeLiveFrame(payload)
  assert.equal(frame.type, 'snapshot')
  if (frame.type !== 'snapshot') return
  assert.equal(frame.items.length, 60)
  assert.equal(frame.items[59].physicalContract, 'P592701')
  assert.equal(frame.items[59].availability, 'unavailable')
})

test('rejects contradictory source, availability, and completed-value identities', () => {
  const frame = (item: unknown) => ({ type: 'snapshot', schema_version: 1, observed_at: '2026-09-13T02:31:01Z', scope: 'operational', items: [item] })
  assert.throws(() => normalizeMarketHomeLiveFrame(frame(quote({ physical_contract: null }))))
  assert.throws(() => normalizeMarketHomeLiveFrame(frame(quote({ source: 'completed_1d', availability: 'live' }))))
  assert.throws(() => normalizeMarketHomeLiveFrame(frame(quote({ source: 'none', availability: 'historical' }))))
  assert.throws(() => normalizeMarketHomeLiveFrame(frame(quote({ availability: 'unavailable', source: 'none', price: null, bar_end: null, reason: null }))))
  assert.throws(() => normalizeMarketHomeLiveFrame(frame(quote({ availability: 'unavailable', source: 'none', trading_day: null, bar_end: null, price: '1', previous_close: null, price_change: null, reason: 'PRICE_UNAVAILABLE' }))))
})

test('applies reset atomically and ignores messages from an older socket generation', () => {
  const sockets: FakeSocket[] = []
  const live = useMarketHomeLive({ createWebSocket: () => { const socket = new FakeSocket(); sockets.push(socket); return socket }, scheduleReconnect: () => 1, clearReconnect: () => {} })
  live.start()
  sockets[0].message({ type: 'snapshot', schema_version: 1, observed_at: '2026-09-13T02:31:01Z', scope: 'operational', items: [quote()] })
  assert.equal(live.items.value.get('ag')?.physicalContract, 'AG2612')
  sockets[0].message({ type: 'reset', schema_version: 1, observed_at: '2026-09-13T02:32:01Z', reason: 'AUTHORITY_CHANGED', items: [quote({ physical_contract: 'AG2701', trading_day: '2026-09-14' })] })
  assert.equal(live.items.value.get('ag')?.physicalContract, 'AG2701')
  live.restart()
  sockets[0].message({ type: 'quote', schema_version: 1, observed_at: '2026-09-13T02:33:01Z', item: quote({ physical_contract: 'AG2612' }) })
  assert.equal(live.items.value.get('ag')?.physicalContract, 'AG2701')
  live.dispose()
})

test('requires a snapshot before quotes and rejects out-of-order or cross-identity quotes', () => {
  const sockets: FakeSocket[] = []
  const live = useMarketHomeLive({ createWebSocket: () => { const socket = new FakeSocket(); sockets.push(socket); return socket }, scheduleReconnect: () => 1, clearReconnect: () => {} })
  live.start()
  sockets[0].message({ type: 'quote', schema_version: 1, observed_at: '2026-09-13T02:30:01Z', item: quote() })
  assert.equal(live.items.value.size, 0)
  sockets[0].message({ type: 'snapshot', schema_version: 1, observed_at: '2026-09-13T02:31:01Z', scope: 'operational', items: [quote()] })
  sockets[0].message({ type: 'quote', schema_version: 1, observed_at: '2026-09-13T02:32:01Z', item: quote({ bar_end: '2026-09-13T02:30:00Z', price: '7000' }) })
  sockets[0].message({ type: 'quote', schema_version: 1, observed_at: '2026-09-13T02:33:01Z', item: quote({ physical_contract: 'AG2701', price: '9000' }) })
  sockets[0].message({ type: 'quote', schema_version: 1, observed_at: '2026-09-13T02:34:01Z', item: quote({ symbol: 'jm', physical_contract: 'JM2701', price: '9000' }) })
  assert.equal(live.items.value.get('ag')?.price, 8123.5)
  assert.equal(live.items.value.get('ag')?.physicalContract, 'AG2612')
  live.dispose()
})

test('ignores an older frame observed after a newer accepted quote', () => {
  const sockets: FakeSocket[] = []
  const live = useMarketHomeLive({ createWebSocket: () => { const socket = new FakeSocket(); sockets.push(socket); return socket } })
  live.start()
  sockets[0].message({ type: 'snapshot', schema_version: 1, observed_at: '2026-09-13T02:31:01Z', scope: 'operational', items: [quote()] })
  sockets[0].message({ type: 'quote', schema_version: 1, observed_at: '2026-09-13T02:33:01Z', item: quote({ bar_end: '2026-09-13T02:33:00Z', price: '8300' }) })
  sockets[0].message({ type: 'snapshot', schema_version: 1, observed_at: '2026-09-13T02:32:01Z', scope: 'operational', items: [quote({ price: '7000' })] })
  assert.equal(live.items.value.get('ag')?.price, 8300)
  assert.equal(live.observedAt.value, '2026-09-13T02:33:01Z')
  live.dispose()
})

test('keeps last values stale on disconnect, reconnects once, and releases resources', () => {
  const sockets: FakeSocket[] = []
  const callbacks: Array<() => void> = []
  const cleared: unknown[] = []
  const live = useMarketHomeLive({ createWebSocket: () => { const socket = new FakeSocket(); sockets.push(socket); return socket }, scheduleReconnect: (callback) => { callbacks.push(callback); return callbacks.length }, clearReconnect: (handle) => cleared.push(handle) })
  live.start()
  sockets[0].message({ type: 'snapshot', schema_version: 1, observed_at: '2026-09-13T02:31:01Z', scope: 'operational', items: [quote()] })
  sockets[0].closeFromServer()
  assert.equal(live.stale.value, true)
  assert.equal(live.items.value.get('ag')?.price, 8123.5)
  assert.equal(callbacks.length, 1)
  assert.equal(live.connection.value, 'stale')
  callbacks[0]()
  assert.equal(sockets.length, 2)
  live.dispose()
  assert.equal(sockets[1].closed, true)
  assert.deepEqual(cleared, [])
})

test('uses bounded 10s-to-60s backoff and exposes unavailable after the retry budget', () => {
  const sockets: FakeSocket[] = []
  const callbacks: Array<() => void> = []
  const delays: number[] = []
  const live = useMarketHomeLive({
    createWebSocket: () => { const socket = new FakeSocket(); sockets.push(socket); return socket },
    scheduleReconnect: (callback, delay) => { callbacks.push(callback); delays.push(delay); return callbacks.length },
    clearReconnect: () => {},
  })
  live.start()
  for (let index = 0; index < 6; index += 1) {
    sockets.at(-1)!.closeFromServer()
    callbacks.at(-1)!()
  }
  sockets.at(-1)!.closeFromServer()
  assert.deepEqual(delays, [10_000, 20_000, 40_000, 60_000, 60_000, 60_000])
  assert.equal(live.connection.value, 'unavailable')
  live.dispose()
})

class FakeSocket {
  onmessage: ((event: { data: string }) => void) | null = null
  onclose: (() => void) | null = null
  closed = false
  message(value: unknown) { this.onmessage?.({ data: JSON.stringify(value) }) }
  closeFromServer() { this.onclose?.() }
  close() { this.closed = true }
}
