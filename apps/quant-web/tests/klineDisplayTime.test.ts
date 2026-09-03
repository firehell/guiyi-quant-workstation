import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { describe, it } from 'node:test'

const chartSource = readFileSync(
  new URL('../src/components/kline/KlineChart.vue', import.meta.url),
  'utf8',
)
const hoverSource = readFileSync(
  new URL('../src/components/kline/KlineHoverLegend.vue', import.meta.url),
  'utf8',
)

describe('KlineChart opening-time presentation', () => {
  it('uses the shared opening-time coordinate for intraday chart data', () => {
    assert.match(chartSource, /toKlineDisplayTimeForPeriod/)
    assert.match(
      chartSource,
      /return toKlineDisplayTimeForPeriod\(bar, props\.period\) as Time/,
    )
  })

  it('passes the selected period to the hover legend', () => {
    assert.match(chartSource, /<KlineHoverLegend\s+[\s\S]*:period="period"/)
    assert.match(hoverSource, /period: string/)
  })

  it('locates focused actions by their formal bar end before using the display coordinate', () => {
    assert.match(
      chartSource,
      /renderedBars\.findIndex\(\(bar\) => Date\.parse\(bar\.time\) === parsed\)/,
    )
  })
})
