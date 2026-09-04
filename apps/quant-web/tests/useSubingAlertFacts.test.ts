import assert from 'node:assert/strict'
import test from 'node:test'
import { useSubingAlertFacts } from '../src/composables/useSubingAlertFacts.ts'

const runtime = { components: { alert: { status: 'ok', enabled_rule_count: 0, rule_status: { htdy_original_15m: { last_evaluated_bar_at: null, last_event_at: null, last_failure_at: null, error_type: null }, subing_ths_alert_15m_v1: { last_evaluated_bar_at: null, last_event_at: null, last_failure_at: null, error_type: null } } } } } as const

test('projects read-only Rule, Scope, and exact runtime facts for SuBing', async () => {
  const facts = useSubingAlertFacts({ fetchRuntime: async () => runtime, fetchProductAlerts: async () => ({ symbol: 'jm', rules: [{ rule_code: 'subing_ths_alert_15m_v1', display_name: '苏冰预警', kind: 'indicator_observation' as const, input_frequencies: ['15m'], enabled_for_product: false, enabled_frequencies: [] }] }) })
  await facts.refresh({ symbol: 'jm', frequency: '15m' })
  assert.match(facts.rule.value ?? '', /状态不可判定/)
  assert.match(facts.rule.value ?? '', /当前 Scope 未启用/)
  assert.match(facts.rule.value ?? '', /苏冰预警/)
  assert.match(facts.rule.value ?? '', /subing_ths_alert_15m_v1/)
  assert.match(facts.rule.value ?? '', /enabled_frequencies=无/)
  assert.equal(facts.runtimeUnavailable.value, false)
})

test('fails closed on malformed product identity or runtime schema', async () => {
  const facts = useSubingAlertFacts({ fetchRuntime: async () => ({ components: { alert: { status: 'ok' } } }) as never, fetchProductAlerts: async () => ({ symbol: 'other', rules: [] }) })
  await facts.refresh({ symbol: 'jm', frequency: '15m' })
  assert.equal(facts.ruleUnavailable.value, true)
  assert.equal(facts.runtimeUnavailable.value, true)
})

test('clears old identity facts while the next product refresh is pending', async () => {
  const rbRules = deferred<{ symbol: string; rules: Array<{ rule_code: 'subing_ths_alert_15m_v1'; display_name: '苏冰预警'; kind: 'indicator_observation'; input_frequencies: ['15m']; enabled_for_product: boolean; enabled_frequencies: ['15m'] }> }>()
  const facts = useSubingAlertFacts({
    fetchRuntime: async () => runtime,
    fetchProductAlerts: async (symbol) => symbol === 'jm'
      ? { symbol: 'jm', rules: [{ rule_code: 'subing_ths_alert_15m_v1', display_name: '苏冰预警', kind: 'indicator_observation' as const, input_frequencies: ['15m'] as ['15m'], enabled_for_product: true, enabled_frequencies: ['15m'] as ['15m'] }] }
      : rbRules.promise,
  })
  await facts.refresh({ symbol: 'jm', frequency: '15m' })
  const pending = facts.refresh({ symbol: 'rb', frequency: '15m' })
  assert.equal(facts.rule.value, null)
  assert.equal(facts.ruleUnavailable.value, true)
  rbRules.resolve({ symbol: 'rb', rules: [{ rule_code: 'subing_ths_alert_15m_v1', display_name: '苏冰预警', kind: 'indicator_observation', input_frequencies: ['15m'], enabled_for_product: true, enabled_frequencies: ['15m'] }] })
  await pending
  assert.match(facts.rule.value ?? '', /RB 15m/)
})

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((done) => { resolve = done })
  return { promise, resolve }
}
