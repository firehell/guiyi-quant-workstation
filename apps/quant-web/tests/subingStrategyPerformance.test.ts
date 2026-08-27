import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'

const root = path.resolve(import.meta.dirname, '..')

test('product detail owns one always-visible fixed actual-dominant 15m performance panel', () => {
  const chart = fs.readFileSync(path.join(root, 'src/pages/market/chart.vue'), 'utf8')
  const panel = fs.readFileSync(path.join(root, 'src/components/market/SubingStrategyPerformancePanel.vue'), 'utf8')
  const api = fs.readFileSync(path.join(root, 'src/api/market.ts'), 'utf8')

  assert.match(chart, /<SubingStrategyPerformancePanel/)
  assert.match(chart, /:symbol="symbol"/)
  assert.match(panel, /真实主力 · 15m · 全历史/)
  assert.match(panel, /参考变动/)
  assert.match(api, /subing-strategy\/performance/)
})

test('sidebar no longer owns complete historical strategy records', () => {
  const panel = fs.readFileSync(path.join(root, 'src/components/market/SubingPanel.vue'), 'utf8')
  assert.doesNotMatch(panel, /<SubingStrategyRecords/)
  assert.match(panel, /当前策略状态/)
})
