import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const source = readFileSync(new URL('../src/components/market/detail/newow/NewowCupFactsPanel.vue', import.meta.url), 'utf8')

test('cup facts panel keeps the clean-room and confirmed-structure boundary visible', () => {
  assert.match(source, /归一杯柄候选/)
  assert.match(source, /非牛哇私有原公式/)
  assert.match(source, /已确认结构示意，非完整 K 线/)
  assert.match(source, /当前区段没有已确认杯柄事实；这不表示策略看空/)
  assert.doesNotMatch(source, /<pre>/)
})
