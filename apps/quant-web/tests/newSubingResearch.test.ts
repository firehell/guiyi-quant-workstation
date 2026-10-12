import assert from 'node:assert/strict'
import { test } from 'node:test'
import { decisionMatches, metricText, runStateText, selectionToken, matchingRun, matchingProfile } from '../src/utils/newSubingResearch.ts'

test('blocked result never renders fabricated return or zero trades', () => {
  assert.equal(metricText({ status: 'DATA_INSUFFICIENT' }, 'account_return_pct'), '不可评价')
  assert.equal(metricText({ status: 'EXECUTION_FACTS_MISSING' }, 'closed_trades'), '不可评价')
  assert.equal(runStateText('DATA_INSUFFICIENT'), '数据不足')
  assert.equal(runStateText('COMPLETED'), '历史回放完成')
  assert.equal(runStateText('SEGMENTED'), '合约段分离，年度不可评价')
})

test('completed metrics format display while preserving unavailable fields', () => {
  assert.equal(metricText({ status: 'COMPLETED', account_return_pct: '-2.15' }, 'account_return_pct', '%'), '-2.150%')
  assert.equal(metricText({ status: 'COMPLETED' }, 'account_return_pct', '%'), '未提供')
})

test('decision filter searches reason and facts without replacing source data', () => {
  const decision = { action: 'REJECT', reason: 'NO_OI', side: 'LONG', facts: { oi_change: 'missing' } }
  assert.equal(decisionMatches(decision, 'REJECT', 'oi'), true)
  assert.equal(decisionMatches(decision, 'SETUP', ''), false)
  assert.equal(decisionMatches(decision, 'ALL', 'missing'), true)
})

test('late-response token changes on every run selection', () => {
  assert.notEqual(selectionToken('a', 1), selectionToken('b', 2))
})

test('research metric display rounds only presentation precision', () => {
  const summary = { status: 'COMPLETED', account_return_pct: '-2.1549876543210987654321', max_drawdown_pct: '0.123456789012345678901234567890', final_equity: '100000.125', total_fees: '45.999', closed_trades: 12 }
  assert.equal(metricText(summary, 'account_return_pct', '%'), '-2.155%')
  assert.equal(metricText(summary, 'max_drawdown_pct', '%'), '0.123%')
  assert.equal(metricText(summary, 'final_equity'), '100000.13')
  assert.equal(metricText(summary, 'total_fees'), '46.00')
  assert.equal(metricText(summary, 'closed_trades'), '12')
  assert.equal(summary.max_drawdown_pct, '0.123456789012345678901234567890')
})

test('unknown and unsafe numeric strings retain exact fallback', () => {
  assert.equal(metricText({ status: 'COMPLETED' }, 'final_equity'), '未提供')
  assert.equal(metricText({ status: 'EXECUTION_FACTS_MISSING', final_equity: '100000' }, 'final_equity'), '不可评价')
  assert.equal(metricText({ status: 'COMPLETED', final_equity: '9007199254740993.125' }, 'final_equity'), '9007199254740993.125')
  assert.equal(metricText({ status: 'COMPLETED', final_equity: '1e999' }, 'final_equity'), '1e999')
  assert.equal(metricText({ status: 'COMPLETED', final_equity: '1e-999' }, 'final_equity'), '1e-999')
  assert.equal(metricText({ status: 'COMPLETED', final_equity: 'unknown' }, 'final_equity'), 'unknown')
})

test('selection isolates V1 legacy cash from both V2 accounts and cost', () => {
  const base = { product: 'AL', scenario: 'baseline', strategy_code: 'new_subing_v1' }
  assert.equal(matchingRun(base, 'new_subing_v1', '100000', 'AL', 'baseline'), true)
  assert.equal(matchingRun(base, 'new_subing_v2', '100000', 'AL', 'baseline'), false)
  assert.equal(matchingRun({ ...base, strategy_code: 'new_subing_v2', initial_cash: '1000000' }, 'new_subing_v2', '100000', 'AL', 'baseline'), false)
  assert.equal(matchingRun({ ...base, strategy_code: 'new_subing_v2', initial_cash: '1000000' }, 'new_subing_v2', '1000000', 'AL', 'double_slippage'), false)
  assert.equal(matchingProfile({ ...base, profile_id: 'new_subing_stage_v2_1m', strategy_code: 'new_subing_v2', initial_cash: '1000000' }, 'new_subing_v2', '1000000', 'AL'), true)
})
