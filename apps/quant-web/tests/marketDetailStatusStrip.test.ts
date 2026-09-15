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

test('Free and HTDY put compact status before the chart and long controls after it', () => {
  for (const path of [
    '../src/components/market/detail/free/FreeChartWorkspace.vue',
    '../src/components/market/detail/htdy/HtdyDetailWorkspace.vue',
  ]) {
    const source = read(path)
    assert.match(source, /<MarketDetailStatusStrip/)
    const chartIndex = source.indexOf('ChartStage')
    const indicatorIndex = source.indexOf('workspace__indicators', chartIndex)
    if (indicatorIndex >= 0) assert.ok(indicatorIndex > chartIndex, `${path} controls must follow its chart`)
  }
})
