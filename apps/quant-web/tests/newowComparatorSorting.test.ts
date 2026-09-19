import assert from 'node:assert/strict'
import test from 'node:test'
import { compareNewowDecimalText } from '../src/utils/newowProductViewModel.ts'

test('five-window presentation comparator preserves Decimal ordering without floats', () => {
  assert.ok(compareNewowDecimalText('10.000000000000000001', '9.999999999999999999') > 0)
  assert.ok(compareNewowDecimalText('-1.2', '-1.19') < 0)
  assert.equal(compareNewowDecimalText('001.20', '1.2'), 0)
})
