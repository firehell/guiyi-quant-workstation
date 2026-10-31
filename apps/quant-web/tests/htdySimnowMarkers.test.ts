import assert from 'node:assert/strict'
import test from 'node:test'
import type { MonitorRecord } from '../src/api/simnowMonitor.ts'
import { projectHtdySimnowRecords } from '../src/utils/htdySimnowMarkers.ts'

const at = '2026-10-30T07:00:00Z'
const bars = [{ time: at, physicalContract: 'JM2701', open: 1400, high: 1410, low: 1390, close: 1405, volume: 10 }]
const signal: MonitorRecord = { id: 'signal-row', kind: 'signal', at, product: 'JM', contract: 'JM2701', status: 'BUY', label: '买信号', signal_id: 'signal-1', order_id: null, facts: { bar_end: at, input_hash: 'a'.repeat(64) } }
const order: MonitorRecord = { id: 'order-row', kind: 'order', at, product: 'JM', contract: 'JM2701', status: 'FILLED', label: '成交回报', signal_id: 'signal-1', order_id: 'order-1', facts: { side: 'BUY', offset: 'OPEN' } }
const fill: MonitorRecord = { id: 'fill-row', kind: 'fill', at, product: 'JM', contract: 'JM2701', status: 'RECORDED', label: '实际成交入账', signal_id: 'signal-1', order_id: 'order-1', facts: { price: '1405.5', quantity: '1', fee: '2.5', filled_at: at, native_precision_seconds: '0' } }

test('stable execution identity links a chain but missing formula/frequency cannot override a strategy signal', () => {
  const records = projectHtdySimnowRecords([signal, order, fill], bars, 'jm')
  assert.equal(records.length, 3)
  assert.equal(records[2]!.signalBarEnd, at)
  assert.equal(records[2]!.linkage, 'unverified')
  assert.match(records[2]!.linkageReason, /版本|周期/)
  assert.equal(records[2]!.callout?.price, '1405.5')
  assert.equal(records[2]!.callout?.time, at)
})

test('different contract, nonexact timestamp, pending or second-precision fills are retained without invented coordinates', () => {
  for (const changed of [
    { ...fill, contract: 'JM2609' },
    { ...fill, facts: { ...fill.facts, filled_at: '2026-10-30T07:00:01Z' } },
    { ...fill, status: 'PENDING' },
    { ...fill, facts: { ...fill.facts, native_precision_seconds: '1' } },
  ]) {
    const result = projectHtdySimnowRecords([signal, order, changed], bars, 'JM').at(-1)!
    assert.equal(result.callout, undefined)
    assert.equal(result.marker, undefined)
    assert.ok(result.plotNotice)
  }
})

test('multiple fills, rejected risks and unfilled orders remain independent; foreign products are excluded', () => {
  const risk: MonitorRecord = { ...signal, id: 'risk', kind: 'risk', contract: '', status: 'REJECTED', label: '风控拒绝', facts: { reason: 'MARGIN_CAP' } }
  const rows = projectHtdySimnowRecords([risk, { ...order, status: 'WORKING' }, fill, { ...fill, id: 'fill-2' }, { ...fill, id: 'foreign', product: 'RB', contract: 'RB2701' }], bars, 'JM')
  assert.equal(rows.length, 4)
  assert.equal(rows[0]!.status, 'REJECTED')
  assert.equal(rows[1]!.status, 'WORKING')
  assert.notEqual(rows[2]!.callout?.id, rows[3]!.callout?.id)
})
