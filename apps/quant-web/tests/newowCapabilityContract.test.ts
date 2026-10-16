import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { getNewowProductCapabilities } from '../src/api/newowProduct.ts'

const contracts = JSON.parse(readFileSync(new URL('../../../services/quant-api/app/market_data/newow/capability_contracts.json', import.meta.url), 'utf8')) as Record<string, {
  response: Record<string, unknown>
  intradayScope?: { allowed: string[]; single: boolean }
}>

test('all frozen capability versions retain their exact wire contract and reject scope drift', async () => {
  assert.equal(Object.keys(contracts).length >= 32, true)
  for (const [version, contract] of Object.entries(contracts)) {
    const scope = contract.intradayScope
    const payload = {
      ...contract.response,
      ...(scope ? { intraday_products: scope.single ? [scope.allowed[0]!] : [...scope.allowed].sort() } : {}),
    }
    const accepted = await getNewowProductCapabilities({ request: async () => structuredClone(payload) })
    assert.equal(accepted.schema_version, version)
    for (const mutation of [{ release_stage: 'unknown' }, { unexpected: null }, { open_sections: [] }]) {
      await assert.rejects(getNewowProductCapabilities({ request: async () => ({ ...payload, ...mutation }) }), { code: 'NEWOW_RESPONSE_INVALID' })
    }
    if (scope) {
      for (const products of [[], ['unknown'], [scope.allowed[0], scope.allowed[0]]]) {
        await assert.rejects(getNewowProductCapabilities({ request: async () => ({ ...payload, intraday_products: products }) }), { code: 'NEWOW_RESPONSE_INVALID' })
      }
    }
    if (accepted.weekly_products) {
      await assert.rejects(getNewowProductCapabilities({ request: async () => ({ ...payload, weekly_products: [...accepted.weekly_products!].reverse() }) }), { code: 'NEWOW_RESPONSE_INVALID' })
    }
  }
})
