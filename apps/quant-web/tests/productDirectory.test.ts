import assert from 'node:assert/strict'
import { describe, it } from 'node:test'

import * as productDirectory from '../src/utils/productDirectory.ts'

describe('productDirectory', () => {
  it('keeps only sector labels and does not duplicate the active product directory', () => {
    assert.equal('PRODUCT_DIRECTORY' in productDirectory, false)
    assert.equal('describeProduct' in productDirectory, false)
    assert.equal(productDirectory.PRODUCT_SECTORS.length, 10)
  })

  it('accepts known backend sectors and safely groups unknown values as other', () => {
    assert.equal(productDirectory.normalizeProductSector('black'), 'black')
    assert.equal(productDirectory.normalizeProductSector(' new_energy '), 'new_energy')
    assert.equal(productDirectory.normalizeProductSector('unknown'), 'other')
    assert.equal(productDirectory.normalizeProductSector(null), 'other')
    assert.equal(productDirectory.DEFAULT_PRODUCT_SECTOR, 'black')
  })
})
