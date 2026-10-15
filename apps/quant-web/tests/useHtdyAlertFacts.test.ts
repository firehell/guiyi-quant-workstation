import assert from 'node:assert/strict'
import test from 'node:test'
import { useHtdyAlertFacts } from '../src/composables/useHtdyAlertFacts.ts'
import { MARKET_FREQUENCIES, type MarketFrequency } from '../src/types/market.ts'
import type { ProductAlertStateResponse } from '../src/api/alerts.ts'

test('clears old product Scope as soon as the next identity starts loading', async () => {
  let resolveRb!: (value: ProductAlertStateResponse) => void
  const rb = new Promise<ProductAlertStateResponse>(resolve => { resolveRb = resolve })
  const facts = useHtdyAlertFacts({
    fetchRuntime: async () => 'ok',
    fetchProductAlerts: async symbol => symbol === 'jm'
      ? { symbol, rules: [rule(symbol, ['15m'])] } : rb,
  })
  await facts.refresh({ symbol: 'jm', frequency: '15m' })
  const pending = facts.refresh({ symbol: 'rb', frequency: '60m' })
  assert.equal(facts.ruleScope.value, 'HTDY Rule / Scope 暂不可用')
  resolveRb({ symbol: 'rb', rules: [rule('rb', ['60m'])] })
  await pending
  assert.match(facts.ruleScope.value, /RB 60m/)
})

test('rejects a product response for a different symbol', async () => {
  const facts = useHtdyAlertFacts({ fetchRuntime: async () => 'ok', fetchProductAlerts: async () => ({ symbol: 'jm', rules: [rule('jm', ['60m'])] }) })
  await facts.refresh({ symbol: 'rb', frequency: '60m' })
  assert.equal(facts.ruleScope.value, 'HTDY Rule / Scope 暂不可用')
  assert.equal(facts.runtime.value, 'healthy')
})

test('rejects contradictory or malformed Scope facts', async () => {
  for (const invalid of [
    { ...rule('jm', ['15m']), enabled_for_product: false },
    { ...rule('jm', ['15m']), enabled_frequencies: ['unknown'] },
    { ...rule('jm', ['15m']), enabled_frequencies: ['15m', '15m'] },
    { ...rule('jm', ['15m']), kind: 'other' },
  ]) {
    const facts = useHtdyAlertFacts({ fetchRuntime: async () => 'ok', fetchProductAlerts: async () => ({ symbol: 'jm', rules: [invalid] }) as never })
    await facts.refresh({ symbol: 'jm', frequency: '15m' })
    assert.equal(facts.ruleScope.value, 'HTDY Rule / Scope 暂不可用')
  }
})

test('request failure clears current facts and synchronous loader failure is contained', async () => {
  let failed = false
  const facts = useHtdyAlertFacts({
    fetchRuntime: () => { if (failed) throw new Error('offline'); return Promise.resolve('ok') },
    fetchProductAlerts: async () => { if (failed) throw new Error('offline'); return { symbol: 'jm', rules: [rule('jm', ['15m'])] } },
  })
  await facts.refresh({ symbol: 'jm', frequency: '15m' })
  failed = true
  await facts.refresh({ symbol: 'jm', frequency: '15m' })
  assert.equal(facts.runtime.value, 'unavailable')
  assert.equal(facts.ruleScope.value, 'HTDY Rule / Scope 暂不可用')
})

test('dispose prevents pending or future results from publishing facts', async () => {
  let resolve!: (value: ProductAlertStateResponse) => void
  const pending = new Promise<ProductAlertStateResponse>(done => { resolve = done })
  const facts = useHtdyAlertFacts({ fetchRuntime: async () => 'ok', fetchProductAlerts: () => pending })
  const refreshing = facts.refresh({ symbol: 'jm', frequency: '15m' })
  facts.dispose()
  resolve({ symbol: 'jm', rules: [rule('jm', ['15m'])] })
  await refreshing
  await facts.refresh({ symbol: 'jm', frequency: '15m' })
  assert.equal(facts.ruleScope.value, 'HTDY Rule / Scope 暂不可用')
})
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

function rule(symbol: string, enabledFrequencies: MarketFrequency[]) {
  return {
    rule_code: 'htdy_original_15m', display_name: '火天大有', kind: 'indicator_observation' as const,
    input_frequencies: [...MARKET_FREQUENCIES], enabled_for_product: enabledFrequencies.length > 0, enabled_frequencies: enabledFrequencies,
    symbol,
  }
}
