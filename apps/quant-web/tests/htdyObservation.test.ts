import test from 'node:test'
import assert from 'node:assert/strict'
import { buildHtdyAlertMarketQuery, htdyDirectionLabel } from '../src/utils/htdyObservation.ts'

test('HTDY alert deep link binds actual JM contract and live 15m chart', () => {
  const query = buildHtdyAlertMarketQuery({
    id: 7,
    symbol: 'jm',
    actual_contract: 'JM2609',
    bar_end: '2026-07-27T01:15:00Z',
  })
  assert.deepEqual(query, {
    symbol: 'jm',
    contract: 'JM2609',
    period: '15m',
    data_mode: 'live',
    access_mode: 'browser',
    time: '2026-07-27T01:15:00Z',
    htdy_alert_id: '7',
  })
})

test('HTDY directions use observation language', () => {
  assert.equal(htdyDirectionLabel('long'), '买多观察')
  assert.equal(htdyDirectionLabel('short'), '卖空观察')
  assert.equal(htdyDirectionLabel('conflict'), '多空冲突观察')
})
