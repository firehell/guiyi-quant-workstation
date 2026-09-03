import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

import { parse } from '@vue/compiler-sfc'

const componentUrl = new URL('../src/components/market/detail/TrendDetailWorkspace.vue', import.meta.url)
const viewModelUrl = new URL('../src/utils/newowViewModel.ts', import.meta.url)
const historyComponentUrl = new URL('../src/components/market/detail/MarketDetailSectionTabs.vue', import.meta.url)

function component() {
  const source = readFileSync(componentUrl, 'utf8')
  const parsed = parse(source, { filename: componentUrl.pathname })
  assert.deepEqual(parsed.errors, [], 'TrendDetailWorkspace must be a valid Vue SFC')
  assert.ok(parsed.descriptor.scriptSetup, 'TrendDetailWorkspace must expose a typed setup contract')
  assert.ok(parsed.descriptor.template, 'TrendDetailWorkspace must render a template')
  return { source, template: parsed.descriptor.template.content }
}

test('projects one Newow snapshot into facts, disclosures, chart, and history without another authority', () => {
  const { source, template } = component()

  assert.match(source, /useNewowTrendDetail/)
  assert.match(source, /buildNewowDetailViewModel/)
  assert.match(source, /model\.value\.history/)
  assert.match(source, /loader\.data\.value/)
  assert.match(source, /onBeforeUnmount\(loader\.dispose\)/)
  assert.match(template, /<MarketDetailFactStrip[^>]+:facts="model\.facts"/)
  assert.match(template, /<MarketDetailInsightDeck[^>]+:sections="disclosureSections"/)
  assert.match(template, /<NewowTrendChartStage[^>]+:data="loader\.data\.value"[^>]+:generic-bars="bars"/s)
  assert.match(template, /<MarketDetailSectionTabs[^>]+:history="model\.history"/s)
  assert.doesNotMatch(source, /getAlert|usePersistentAlert|useHtdy|useRangeDetector|ResearchOverlayId/)
  assert.doesNotMatch(template, /MACD|EMA|Range|火天大有|苏冰|预警/)
})

test('keeps the three facts and all authority disclosures visible before the independent chart', () => {
  const { source, template } = component()
  const banner = template.indexOf('model.semanticBanner.text')
  const facts = template.indexOf('<MarketDetailFactStrip')
  const notices = template.indexOf('trend-workspace__notices')
  const disclosures = template.indexOf('<MarketDetailInsightDeck')
  const chart = template.indexOf('<NewowTrendChartStage')

  assert.ok(banner >= 0 && banner < facts)
  assert.ok(facts < notices && notices < disclosures && disclosures < chart)
  assert.match(readFileSync(viewModelUrl, 'utf8'), /建仓、持有、清仓、空仓为趋势引擎状态，不代表实际账户持仓。/)
  assert.match(source, /calculation_identity/)
  assert.match(source, /source_identity/)
  assert.match(source, /formula_descriptions/)
  assert.match(source, /bar_policy/)
  assert.match(source, /rollover_seams/)
  assert.match(source, /warnings/)
  assert.match(source, /仅展示已完成 D1/)
  assert.match(source, /不表示建立期货空单/)
})

test('fails Newow closed while retaining only the generic completed-D1 chart fallback', () => {
  const { source, template } = component()

  assert.match(source, /趋势策略数据不可用/)
  assert.match(source, /基础 completed D1 K 线/)
  assert.match(template, /loader\.error\.value/)
  assert.match(template, /data-newow-state="unavailable"/)
  assert.match(template, /:data="loader\.data\.value"/)
  assert.match(template, /:generic-bars="bars"/)
  assert.doesNotMatch(template, /overlay|load-earlier|focus-bar-end/i)
})

test('distinguishes the one-shot Newow loading state from an unavailable result', () => {
  const { source, template } = component()

  assert.match(template, /loader\.loading\.value\s*\?\s*'loading'/)
  assert.match(source, /const notices = computed\(\(\) => buildNotices\([\s\S]+?loader\.loading\.value/)
  assert.match(source, /正在读取 Newow 趋势数据；读取完成前仅显示基础 completed D1 K 线。/)
  assert.match(template, /v-if="loader\.error\.value"/)
})

test('exposes history availability and the existing history opener without alert semantics', () => {
  const { source } = component()
  const historySource = readFileSync(historyComponentUrl, 'utf8')

  assert.match(source, /'history-availability':\s*\[available:\s*boolean\]/)
  assert.match(source, /watch\(\(\) => model\.value\.history\.length/)
  assert.match(source, /tabs\.value\?\.openHistory\(\)/)
  assert.match(source, /defineExpose\(\{ openHistory \}\)/)
  assert.doesNotMatch(source, /notificationAttemptedAt|AlertEvent|open-alert|manageAlert/)
  assert.match(historySource, /item\.markerType/)
  assert.match(historySource, /item\.formulaVersion/)
})
