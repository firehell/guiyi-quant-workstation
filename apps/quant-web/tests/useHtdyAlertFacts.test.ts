import assert from 'node:assert/strict'
import test from 'node:test'
test('drops a late JM Runtime and Scope response after identity switches to RB', async () => {
  const { useHtdyAlertFacts } = await import('../src/composables/useHtdyAlertFacts.ts')
  const pending: Array<(value: unknown) => void> = []
  const controller = useHtdyAlertFacts({
    fetchRuntime: () => new Promise((resolve) => pending.push(resolve)),
    fetchProductAlerts: () => new Promise((resolve) => pending.push(resolve)),
  })
  const jm = controller.refresh({ symbol: 'jm', frequency: '15m' })
  const rb = controller.refresh({ symbol: 'rb', frequency: '60m' })
  pending[2]!('ok')
  pending[3]!({ symbol: 'rb', rules: [rule('rb', ['60m'])] })
  await rb
  pending[0]!('degraded')
  pending[1]!({ symbol: 'jm', rules: [rule('jm', ['15m'])] })
  await jm
  assert.equal(controller.runtime.value, 'healthy')
  assert.match(controller.ruleScope.value, /RB 60m/)
  assert.doesNotMatch(controller.ruleScope.value, /JM 15m/)
})

function rule(symbol: string, enabledFrequencies: string[]) {
  return {
    rule_code: 'htdy_original_15m', display_name: '火天大有', kind: 'indicator_observation',
    input_frequencies: ['15m'], enabled_for_product: enabledFrequencies.length > 0, enabled_frequencies: enabledFrequencies,
    symbol,
  }
}
