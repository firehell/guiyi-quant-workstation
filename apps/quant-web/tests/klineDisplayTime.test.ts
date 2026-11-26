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
  it('preserves opening-time coordinates outside the shared detail canvas', () => {
    assert.match(chartSource, /toKlineDisplayTimeForPeriod/)
    assert.match(
      chartSource,
      /toKlineDisplayTimeForPeriod\(bar, props\.period\) as Time/,
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

  it('reapplies the current EMA palette whenever derived series render', () => {
    assert.match(chartSource, /emaColors = \{ ema_10: theme\.ema10, ema_21: theme\.ema21, ema_60: theme\.ema60 \}/)
    assert.match(chartSource, /for \(const indicator of EMA_INDICATORS\)/)
    assert.match(chartSource, /series\.applyOptions\(\{ color: emaColors\[indicator\] \}\)/)
  })
})
