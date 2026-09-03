import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

import { parse } from '@vue/compiler-sfc'

const componentNames = [
  'MarketDetailTopBar',
  'MarketDetailQuoteHeader',
  'MarketFactsDisclosure',
  'MarketDetailViewNav',
  'MarketDetailFactStrip',
  'MarketDetailInsightDeck',
  'MarketDetailDisclosure',
  'MarketDetailSectionTabs',
  'MarketDetailDrawer',
  'MarketDetailUnavailable',
  'MarketKlineStage',
] as const

function componentSource(name: (typeof componentNames)[number]): string {
  return readFileSync(new URL(`../src/components/market/detail/${name}.vue`, import.meta.url), 'utf8')
}

function parsedComponent(name: (typeof componentNames)[number]) {
  const source = componentSource(name)
  const parsed = parse(source, { filename: `${name}.vue` })
  assert.deepEqual(parsed.errors, [], `${name} must be a valid Vue SFC`)
  assert.ok(parsed.descriptor.scriptSetup, `${name} must expose a typed script setup contract`)
  assert.ok(parsed.descriptor.template, `${name} must render a template`)
  return { source, template: parsed.descriptor.template.content }
}

test('all Slice A shell primitives are valid typed Vue components', () => {
  for (const name of componentNames) parsedComponent(name)
})

test('top bar keeps text semantics and capability-gates alert actions', () => {
  const { source, template } = parsedComponent('MarketDetailTopBar')
  for (const event of ['back', 'select-symbol', 'open-history', 'open-alert', 'open-more']) {
    assert.match(source, new RegExp(`(?:'${event}'|${event}):`))
  }
  assert.match(template, /aria-label="返回"/)
  assert.match(template, /aria-label="历史记录"/)
  assert.match(template, /aria-label="更多"/)
  assert.match(template, /role="group" aria-label="详情页操作"/)
  assert.match(template, /canManageAlert/)
  assert.match(template, />\s*预警\s*</)
  assert.doesNotMatch(template, /收藏|star/i)
})

test('view navigation retains the four business names and emits exact identities', () => {
  const { source, template } = parsedComponent('MarketDetailViewNav')
  for (const label of ['趋势策略', '火天大有', '新苏冰', '自由看盘']) {
    assert.match(source, new RegExp(label))
  }
  assert.match(source, /select:\s*\[identity:\s*MarketDetailIdentity\]/)
  assert.match(template, /v-if="showSeriesControls"/)
  assert.match(template, /v-if="showFrequencyControls"/)
  assert.match(template, /role="group" aria-label="序列"/)
  assert.match(template, /role="group" aria-label="周期"/)
  assert.doesNotMatch(template, /disabled/)
})

test('facts and disclosures preserve the strict presentation contract', () => {
  const facts = parsedComponent('MarketDetailFactStrip')
  const disclosure = parsedComponent('MarketDetailDisclosure')
  const deck = parsedComponent('MarketDetailInsightDeck')

  assert.match(facts.source, /exactly three market detail facts/i)
  assert.match(disclosure.template, /aria-expanded/)
  assert.match(disclosure.template, /aria-controls/)
  assert.match(disclosure.template, /MarketDetailIcon[^>]+chevron/)
  assert.match(deck.source, /matchMedia\('\(max-width: 480px\)'\)/)
})

test('market facts disclose status before expansion and close on identity change', () => {
  const { source, template } = parsedComponent('MarketFactsDisclosure')
  assert.match(source, /watch\(\(\) => props\.identityKey/)
  assert.match(template, /freshnessLabel/)
  assert.match(template, /aria-expanded/)
  assert.match(template, /aria-controls/)
})

test('history uses one source and mobile drawer restores focus', () => {
  const tabs = parsedComponent('MarketDetailSectionTabs')
  const drawer = parsedComponent('MarketDetailDrawer')

  assert.equal((tabs.source.match(/history:\s*readonly MarketDetailHistoryItem\[\]/g) ?? []).length, 1)
  assert.match(tabs.template, /v-if="history\.length > 0"/)
  assert.match(tabs.template, /<MarketDetailDrawer/)
  assert.match(drawer.source, /previousFocus/)
  assert.match(drawer.source, /event\.key === 'Escape'/)
  assert.match(drawer.source, /event\.key !== 'Tab'/)
  assert.match(drawer.source, /onMounted\(\(\) => syncOpen\(props\.open\)\)/)
  assert.match(drawer.template, /role="dialog"/)
  assert.match(drawer.template, /aria-modal="true"/)
})

test('the shared K-line stage uses the registered clean-room action icons', () => {
  const { source, template } = parsedComponent('MarketKlineStage')
  assert.match(source, /MarketDetailIcon/)
  assert.match(template, /name="refresh"/)
  assert.match(template, /name="fullscreen"/)
  assert.doesNotMatch(template, /↺|⛶/)
})
