import assert from 'node:assert/strict'
import test from 'node:test'
import { projectMarketHomeLiveRows } from '../src/utils/marketHomeLiveView.ts'

const row = { symbol: 'ag', actual_contract: 'AG2612', close: 8000, price_change_1d: 0.01, dailyState: 'up', weeklyState: 'down' }
const live = { symbol: 'ag', physicalContract: 'AG2612', tradingDay: '2026-09-13', barEnd: '2026-09-13T02:31:00Z', price: 8123.5, previousClose: 8000, priceChange: 0.0154375, source: 'completed_1m', availability: 'live', phase: 'TRADING', reason: null }

test('projects same-contract completed price without mutating the overview snapshot', () => {
  const result = projectMarketHomeLiveRows([row], new Map([['ag', live]]))
  assert.equal(result[0].close, 8123.5)
  assert.equal(result[0].price_change_1d, 0.0154375)
  assert.equal(result[0].liveQuote?.source, 'completed_1m')
  assert.equal(row.close, 8000)
})

test('uses a backend-authorized rollover quote without rewriting completed D1 and W1 facts', () => {
  const result = projectMarketHomeLiveRows([row], new Map([['ag', {
    ...live,
    physicalContract: 'AG2701',
    price: 8200,
    previousClose: null,
    priceChange: null,
  }]]))[0]
  assert.equal(result.close, 8200)
  assert.equal(result.price_change_1d, null)
  assert.equal(result.liveQuote?.physicalContract, 'AG2701')
  assert.equal(result.actual_contract, 'AG2612')
  assert.equal(result.dailyState, 'up')
  assert.equal(result.weeklyState, 'down')
})

test('keeps completed D1 facts when the live item is unavailable', () => {
  const unavailable = projectMarketHomeLiveRows([row], new Map([['ag', { ...live, physicalContract: null, tradingDay: null, barEnd: null, price: null, previousClose: null, priceChange: null, source: 'none', availability: 'unavailable', reason: 'NO_COMPLETED_VALUE' }]]))
  assert.equal(unavailable[0].close, 8000)
  assert.equal(unavailable[0].liveQuote, null)
})
