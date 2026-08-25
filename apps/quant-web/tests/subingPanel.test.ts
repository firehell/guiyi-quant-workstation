import assert from 'node:assert/strict'
import { existsSync, readFileSync } from 'node:fs'
import test from 'node:test'

const panelUrl = new URL('../src/components/market/SubingPanel.vue', import.meta.url)
const panelSource = existsSync(panelUrl) ? readFileSync(panelUrl, 'utf-8') : ''
test('keeps the single panel free of retired presentation imports', () => {
  assert.equal(existsSync(panelUrl), true)
  assert.doesNotMatch(panelSource, /SubingLifecyclePanel|SubingResearchSection/)
})

test('contains presentation formatting only and no browser Factor Signal or Lifecycle formula', () => {
  assert.doesNotMatch(
    panelSource,
    /buildKlineDerivedData|calculate(?:Factor|Signal|Lifecycle)|compute(?:Factor|Signal|Lifecycle)|reduce\(|ema\(|macd\(|slope_5_raw|slope_10_raw/i,
  )
})
