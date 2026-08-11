import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { describe, it } from 'node:test'

import * as productDirectory from '../src/utils/productDirectory.ts'

function activeSymbols(): string[] {
  return readFileSync(new URL('../../../data/universe/active_products.txt', import.meta.url), 'utf8')
    .split(/\r?\n/)
    .map((symbol) => symbol.trim())
    .filter(Boolean)
    .sort()
}

describe('productDirectory', () => {
  it('covers every active product exactly once with a Chinese name and one sector', () => {
    const directory = productDirectory as Record<string, unknown>
    assert.equal(typeof directory.PRODUCT_DIRECTORY, 'object')
    assert.equal(typeof directory.describeProduct, 'function')
    if (!directory.PRODUCT_DIRECTORY || typeof directory.describeProduct !== 'function') return

    const entries = directory.PRODUCT_DIRECTORY as Record<string, { name: string; sector: string }>
    assert.deepEqual(Object.keys(entries).sort(), activeSymbols())
    assert.equal(new Set(Object.keys(entries)).size, activeSymbols().length)
    for (const entry of Object.values(entries)) {
      assert.match(entry.name, /[\u3400-\u9fff]/)
      assert.notEqual(entry.sector, '')
    }
  })

  it('uses the agreed display names and sector boundaries', () => {
    const directory = productDirectory as Record<string, unknown>
    const describe = directory.describeProduct
    assert.equal(typeof describe, 'function')
    if (typeof describe !== 'function') return

    assert.deepEqual(describe('jm', 'JM'), { symbol: 'jm', name: '焦煤', sector: 'black' })
    assert.deepEqual(describe('rb', 'RB'), { symbol: 'rb', name: '螺纹钢', sector: 'steel' })
    assert.deepEqual(describe('ag', 'AG'), { symbol: 'ag', name: '白银', sector: 'precious' })
    assert.equal((directory.DEFAULT_PRODUCT_SECTOR as string | undefined), 'black')
  })
})
