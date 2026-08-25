import assert from 'node:assert/strict'
import { existsSync, readFileSync } from 'node:fs'
import test from 'node:test'

const panelUrl = new URL('../src/components/market/SubingPanel.vue', import.meta.url)
const panelSource = existsSync(panelUrl) ? readFileSync(panelUrl, 'utf-8') : ''
const sidebarSource = readFileSync(
  new URL('../src/components/market/ProductCheckSidebar.vue', import.meta.url),
  'utf-8',
)

test('declares the single-product SuBing panel DTO and event contracts', () => {
  assert.equal(existsSync(panelUrl), true)
  for (const contract of [
    'snapshot: SubingResearchResponse | null',
    'supported: boolean',
    'loading: boolean',
    'error: boolean',
    'currentEvents: AlertEvent[]',
    'currentEventStates: Record<number, EventState>',
    'rules: ProductAlertRuleState[]',
    'runtimeStatus: AlertRuntimeStatus | null',
    'savingRuleCodes: Set<string>',
    "'open-formal-event': [event: AlertEvent, state: EventState | null]",
    "'toggle-subing-alert': [ruleCode: string, enabled: boolean]",
  ]) assert.match(panelSource, new RegExp(escapeRegExp(contract)))
})

test('keeps only immutable SuBing Formal Events and forwards the selected event and state unchanged', () => {
  assert.match(
    panelSource,
    /currentEvents\.filter\(\(event\) => event\.rule_code === ALERT_RULE_CODES\.SUBING\)/,
  )
  assert.match(
    panelSource,
    /summarizeFormalEvent\(subingEvents\.value, props\.currentEventStates\)/,
  )
  assert.match(
    panelSource,
    /emit\('open-formal-event', formalEvent\.event, formalEvent\.state\)/,
  )
  assert.doesNotMatch(panelSource, /status="ready"|:loading="false"/)
})

test('prefers the resolved Signal with primary fallback and displays server Factor evidence', () => {
  assert.match(
    panelSource,
    /props\.snapshot\?\.resolved_signal \?\? props\.snapshot\?\.primary_signal \?\? null/,
  )
  for (const label of [
    'Resolved Signal',
    'Primary Signal',
    'Primary 确认',
    'Primary Factor',
    'Companion 确认',
    'Companion Factor',
  ]) assert.match(panelSource, new RegExp(label))
  assert.match(panelSource, /subingSignalLabel/)
  assert.match(panelSource, /`\$\{value\.timeframe\} · \$\{direction\(value\.price_side\)\}/)
  assert.match(panelSource, /snapshot\.primary\.snapshot\.bar_end/)
  assert.match(panelSource, /snapshot\.companion\.snapshot\.bar_end/)
})

test('renders Lifecycle in the same panel and preserves distinct unavailable states', () => {
  const lifecycleIndex = panelSource.indexOf('data-testid="subing-lifecycle-panel"')
  assert.ok(lifecycleIndex > panelSource.indexOf('Primary Factor'))
  assert.match(panelSource, /v-if="!supported"/)
  assert.match(panelSource, /v-else-if="loading"/)
  assert.match(panelSource, /v-else-if="error \|\| !snapshot"/)
  assert.match(panelSource, /primary\.status !== 'ready' \|\| !snapshot\.primary\.snapshot/)
  assert.match(panelSource, /指标 warm-up 中 \/ 数据不足/)
  assert.doesNotMatch(panelSource, /SubingLifecyclePanel|SubingResearchSection/)
})

test('uses only SuBing product Scope and guards its toggle emit by exact Rule code', () => {
  assert.match(panelSource, /subingRule\.enabled_for_product/)
  assert.doesNotMatch(panelSource, /enabled_frequencies/)
  assert.match(panelSource, /if \(ruleCode !== ALERT_RULE_CODES\.SUBING\) return/)
  assert.match(panelSource, /emit\('toggle-subing-alert', ruleCode, enabled\)/)
  assert.doesNotMatch(panelSource, /ALERT_RULE_CODES\.HTDY|htdy_original_15m/)
})

test('keeps one ordered SuBing panel and no duplicated SuBing presentation in the sidebar', () => {
  assert.equal((sidebarSource.match(/<SubingPanel/g) || []).length, 1)
  assert.match(sidebarSource, /:current-events="subingEvents"/)
  assert.match(sidebarSource, /:rules="subingRules"/)
  assert.match(sidebarSource, /@open-formal-event="\(event, state\) => emit\('open-formal-event', event, state\)"/)
  assert.match(sidebarSource, /@toggle-subing-alert="\(ruleCode, enabled\) => emit\('toggle-subing-alert', ruleCode, enabled\)"/)
  assert.doesNotMatch(sidebarSource, /SubingResearchSection|SubingLifecyclePanel/)
  assert.doesNotMatch(sidebarSource, /subingSignalSummary|subingDirections|lifecycleProgress/)
})

test('contains presentation formatting only and no browser Factor Signal or Lifecycle formula', () => {
  assert.doesNotMatch(
    panelSource,
    /buildKlineDerivedData|calculate(?:Factor|Signal|Lifecycle)|compute(?:Factor|Signal|Lifecycle)|reduce\(|ema\(|macd\(|slope_5_raw|slope_10_raw/i,
  )
})

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}
