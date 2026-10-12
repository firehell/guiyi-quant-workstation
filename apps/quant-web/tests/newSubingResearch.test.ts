import assert from 'node:assert/strict'
import { test } from 'node:test'
import { decisionMatches, metricText, runStateText, selectionToken } from '../src/utils/newSubingResearch.ts'

test('blocked result never renders fabricated return or zero trades', () => {
  assert.equal(metricText({ status: 'DATA_INSUFFICIENT' }, 'account_return_pct'), '不可评价')
  assert.equal(metricText({ status: 'EXECUTION_FACTS_MISSING' }, 'closed_trades'), '不可评价')
  assert.equal(runStateText('DATA_INSUFFICIENT'), '数据不足')
  assert.equal(runStateText('COMPLETED'), '历史回放完成')
  assert.equal(runStateText('SEGMENTED'), '合约段分离，年度不可评价')
})

test('completed metrics retain authoritative string values', () => {
  assert.equal(metricText({ status: 'COMPLETED', account_return_pct: '-2.15' }, 'account_return_pct', '%'), '-2.15%')
  assert.equal(metricText({ status: 'COMPLETED' }, 'account_return_pct', '%'), '未提供')
})

test('decision filter searches reason and facts without replacing source data', () => {
  const decision = { action: 'REJECT', reason: 'NO_OI', side: 'LONG', facts: { oi_change: 'missing' } }
  assert.equal(decisionMatches(decision, 'REJECT', 'oi'), true)
  assert.equal(decisionMatches(decision, 'BUILD', ''), false)
  assert.equal(decisionMatches(decision, 'ALL', 'missing'), true)
})

test('late-response token changes on every run selection', () => {
  assert.notEqual(selectionToken('a', 1), selectionToken('b', 2))
})
