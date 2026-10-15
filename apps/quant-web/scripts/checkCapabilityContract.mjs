import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { getNewowProductCapabilities } from '../src/api/newowProduct.ts'

const cases = JSON.parse(readFileSync(0, 'utf8'))
for (const { payload, valid } of cases) {
  let accepted = false
  try { await getNewowProductCapabilities({ request: async () => structuredClone(payload) }); accepted = true }
  catch (error) { assert.equal(error.code, 'NEWOW_RESPONSE_INVALID') }
  assert.equal(accepted, valid, `Capability acceptance differs: ${payload.schema_version}`)
}
console.log(`Actual Web validator checked ${cases.length} capability responses`)
