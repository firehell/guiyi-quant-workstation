import assert from 'node:assert/strict'
import test from 'node:test'
import { newowActionReturnDisplay, newowActionStatus } from '../src/utils/newowActionReturnDisplay.ts'
import type { NewowReferenceTrade } from '../src/types/newowProduct.ts'
const callout = { id: 'exit-1', time: '2026-09-01T15:00:00', physicalContract: 'RB2610', price: '3022', title: '清仓', detail: '参考价 3022', tone: 'loss' as const, above: true }
const trade = { status: 'CLOSED', strategy_code: 'trend', exit_signal_id: callout.id, exit_bar_end: callout.time, exit_reference_price: callout.price, physical_contract: callout.physicalContract, reference_return_pct: '0.4' } as NewowReferenceTrade
test('closed exact exit displays authoritative return with profit/loss colors', () => {
  assert.deepEqual(newowActionReturnDisplay(callout, 'trend', [trade]), { text: '3022(+0.4%)', direction: 'up' })
  assert.deepEqual(newowActionReturnDisplay(callout, 'trend', [{ ...trade, reference_return_pct: '-1.2' }]), { text: '3022(-1.2%)', direction: 'down' })
  assert.deepEqual(newowActionReturnDisplay(callout, 'trend', [{ ...trade, reference_return_pct: '0' }]), { text: '3022(0%)', direction: 'neutral' })
})
test('missing, interrupted, ambiguous and foreign exits never infer returns', () => {
  for (const trades of [[], [trade, trade], [{ ...trade, status: 'OPEN' as const }], [{ ...trade, strategy_code: 'oscillation' as const }], [{ ...trade, exit_signal_id: 'other' }], [{ ...trade, physical_contract: 'RB2701' }], [{ ...trade, exit_bar_end: 'other' }], [{ ...trade, exit_reference_price: '3000' }], [{ ...trade, reference_return_pct: null }]]) {
    assert.deepEqual(newowActionReturnDisplay(callout, 'trend', trades), { text: '3022', direction: 'neutral' })
  }
  assert.deepEqual(newowActionReturnDisplay({ ...callout, above: false }, 'trend', [trade]), { text: '建仓价:3022', direction: 'neutral' })
})

test('pagination and reordered unrelated trades preserve exact single-trade return', () => {
  const unrelated = { ...trade, exit_signal_id: 'another', reference_return_pct: '99' }
  const original = newowActionReturnDisplay(callout, 'trend', [trade])
  assert.deepEqual(newowActionReturnDisplay(callout, 'trend', [unrelated, trade]), original)
  assert.deepEqual(newowActionReturnDisplay(callout, 'trend', [trade, unrelated]), original)
})

test('interruption belongs only to the exact entry and is not closed PnL', () => {
  const entry = { ...callout, above: false }
  const interrupted = { ...trade, entry_signal_id: callout.id, entry_bar_end: callout.time, entry_reference_price: callout.price, status: 'ROLLOVER_INTERRUPTED' as const }
  assert.equal(newowActionStatus(entry, 'trend', [interrupted]), '换月中断')
  assert.equal(newowActionStatus(entry, 'trend', [{ ...interrupted, status: 'DATA_INTERRUPTED' }]), '数据中断')
  assert.equal(newowActionStatus(callout, 'trend', [interrupted]), null)
  assert.equal(newowActionStatus(entry, 'oscillation', [interrupted]), null)
  assert.equal(newowActionReturnDisplay(callout, 'trend', [interrupted]).direction, 'neutral')
})
