import assert from 'node:assert/strict'
import test from 'node:test'
import { summarizeMarketBackground } from '../src/utils/productCheck.ts'

test('market background keeps aligned and conflict semantics explicit', () => {
  assert.deepEqual(summarizeMarketBackground('up', 'up'), { label: '同向偏多', tone: 'up' })
  assert.deepEqual(summarizeMarketBackground('down', 'down'), { label: '同向偏空', tone: 'down' })
  assert.deepEqual(summarizeMarketBackground('neutral', 'neutral'), { label: '中性', tone: 'neutral' })
  assert.deepEqual(summarizeMarketBackground('up', 'neutral'), { label: '未共振', tone: 'warning' })
  assert.deepEqual(summarizeMarketBackground('unavailable', 'up'), { label: '数据不足', tone: 'warning' })
})
