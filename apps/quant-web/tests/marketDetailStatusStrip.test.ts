import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const read = (path: string) => readFileSync(new URL(path, import.meta.url), 'utf8')

test('shared status strip keeps the summary compact and opens one evidence drawer', () => {
  const source = read('../src/components/market/detail/MarketDetailStatusStrip.vue')
  assert.match(source, /查看依据/)
  assert.match(source, /<MarketDetailDrawer/)
  assert.match(source, /<MarketDetailFactStrip/)
  assert.match(source, /role="status"/)
})

test('Free puts direct indicator controls before the chart instead of a status strip', () => {
  const source = read('../src/components/market/detail/free/FreeChartWorkspace.vue')
  assert.doesNotMatch(source, /<MarketDetailStatusStrip/)
  assert.match(source, /aria-label="主图指标"/)
  assert.match(source, /indicator-chip--active/)
  const template = source.slice(source.indexOf('<template>'))
  const chartIndex = template.indexOf('FreeChartStage')
  const indicatorIndex = template.indexOf('free-workspace__indicators')
  assert.ok(indicatorIndex >= 0 && indicatorIndex < chartIndex, 'indicator controls must precede the chart')
  assert.doesNotMatch(read('../src/components/market/detail/htdy/HtdyDetailWorkspace.vue'), /<MarketDetailStatusStrip/)
})
