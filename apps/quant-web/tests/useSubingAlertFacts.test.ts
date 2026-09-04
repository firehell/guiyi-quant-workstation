import assert from 'node:assert/strict'
import test from 'node:test'
import { useSubingAlertFacts } from '../src/composables/useSubingAlertFacts.ts'

const runtime = { components: { alert: { status: 'ok', enabled_rule_count: 0, rule_status: { htdy_original_15m: { last_completed_bar_at: null, last_success_at: null, last_failure_at: null, last_error_type: null }, subing_ths_alert_15m_v1: { last_completed_bar_at: null, last_success_at: null, last_failure_at: null, last_error_type: null } } } } } as const

test('projects read-only Rule, Scope, and exact runtime facts for SuBing', async () => {
  const facts = useSubingAlertFacts({ fetchRuntime: async () => runtime, fetchProductAlerts: async () => ({ symbol: 'jm', rules: [{ rule_code: 'subing_ths_alert_15m_v1', display_name: '苏冰预警', kind: 'indicator_observation' as const, input_frequencies: ['15m'], enabled_for_product: false, enabled_frequencies: [] }] }) })
  await facts.refresh({ symbol: 'jm', frequency: '15m' })
  assert.match(facts.rule.value ?? '', /Rule 已禁用/)
  assert.match(facts.rule.value ?? '', /当前 Scope 未启用/)
  assert.equal(facts.runtimeUnavailable.value, false)
})

test('fails closed on malformed product identity or runtime schema', async () => {
  const facts = useSubingAlertFacts({ fetchRuntime: async () => ({ components: { alert: { status: 'ok' } } }) as never, fetchProductAlerts: async () => ({ symbol: 'other', rules: [] }) })
  await facts.refresh({ symbol: 'jm', frequency: '15m' })
  assert.equal(facts.ruleUnavailable.value, true)
  assert.equal(facts.runtimeUnavailable.value, true)
})
