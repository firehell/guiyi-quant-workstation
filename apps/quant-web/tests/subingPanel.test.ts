import assert from 'node:assert/strict'
import { existsSync, readFileSync } from 'node:fs'
import test from 'node:test'

const panelUrl = new URL('../src/components/market/SubingPanel.vue', import.meta.url)
const panelSource = existsSync(panelUrl) ? readFileSync(panelUrl, 'utf-8') : ''
test('contains presentation formatting only and no browser Factor Signal or Lifecycle formula', () => {
  assert.doesNotMatch(
    panelSource,
    /buildKlineDerivedData|calculate(?:Factor|Signal|Lifecycle)|compute(?:Factor|Signal|Lifecycle)|reduce\(|ema\(|macd\(|slope_5_raw|slope_10_raw/i,
  )
})

test('moves Strategy records behind chart settings while sidebar keeps confirm facts and Lifecycle opt-in', () => {
  const chartSource = readFileSync(
    new URL('../src/pages/market/chart.vue', import.meta.url),
    'utf-8',
  )
  const toolbarSource = readFileSync(
    new URL('../src/components/market/ProductWorkspaceToolbar.vue', import.meta.url),
    'utf-8',
  )

  assert.doesNotMatch(panelSource, /<SubingStrategyRecords/)
  assert.match(panelSource, /data-testid="subing-strategy-event"/)
  assert.match(panelSource, /formatConfirmEffectiveTime/)
  assert.match(panelSource, /confirmValidityLabel/)
  assert.doesNotMatch(panelSource, /data-testid="subing-current-strategy-state"/)
  assert.match(chartSource, /<SubingStrategyPerformancePanel/)
  assert.match(chartSource, /v-if="showSubingStrategyPerformance"/)
  assert.match(toolbarSource, /显示全历史策略效果/)
  assert.match(panelSource, /data-testid="subing-research-details"/)
  assert.match(panelSource, /<summary>当前研究 \/ 数据身份 \/ 详细信息<\/summary>/)
  assert.doesNotMatch(
    readFileSync(new URL('../src/components/market/SubingStrategyRecords.vue', import.meta.url), 'utf-8'),
    /supported:/,
  )
  assert.match(panelSource, /showInternalProcess && lifecycle/)
  assert.match(chartSource, /if \(!showSubingInternalProcess\.value\) return \[\]/)
  assert.match(chartSource, /historicalResearchMarkers\.value/)
  assert.match(toolbarSource, /显示苏冰内部研究过程/)
  assert.match(toolbarSource, /默认关闭；仅显示当前准备 \/ 研究确认 \/ 风险 \/ 结束事实/)
})

test('renders trigger and protective lifecycle pivots as distinct formatted facts', () => {
  assert.match(panelSource, /buildSubingLifecyclePivotFacts/)
  assert.match(panelSource, /lifecyclePivotFacts/)
  assert.match(panelSource, /pivotFact\.label/)
  assert.match(panelSource, /pivotFact\.price/)
  assert.doesNotMatch(panelSource, /lifecycle\.bound_reference_pivot\.price/)
})
