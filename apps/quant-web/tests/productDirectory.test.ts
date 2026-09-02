import assert from 'node:assert/strict'
import { describe, it } from 'node:test'

import * as productDirectory from '../src/utils/productDirectory.ts'
import type { DominantContractItem } from '../src/types/market.ts'

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

  it('renders backend sector codes with the shared Chinese label', () => {
    assert.equal(typeof productDirectory.productSectorLabel, 'function')
    assert.equal(productDirectory.productSectorLabel('black'), '黑色系')
    assert.equal(productDirectory.productSectorLabel('agriculture'), '农产品')
    assert.equal(productDirectory.productSectorLabel('unknown'), '航运/其他')
  })

  it('groups the backend dominant list in sector order and keeps product codes sorted', () => {
    const items: DominantContractItem[] = [
      { product: 'au', product_name: '黄金', sector: 'precious', exchange: 'SHFE', actual_contract: 'AU2601', dominant_mapping_date: '2026-09-02' },
      { product: 'rb', product_name: '螺纹钢', sector: 'black', exchange: 'SHFE', actual_contract: 'RB2601', dominant_mapping_date: '2026-09-02' },
      { product: 'zz', product_name: '未知品种', sector: 'unknown', exchange: 'TEST', actual_contract: 'ZZ2601', dominant_mapping_date: '2026-09-02' },
      { product: 'cu', product_name: '沪铜', sector: 'nonferrous', exchange: 'SHFE', actual_contract: 'CU2601', dominant_mapping_date: '2026-09-02' },
      { product: 'ag', product_name: '白银', sector: 'precious', exchange: 'SHFE', actual_contract: 'AG2601', dominant_mapping_date: '2026-09-02' },
    ]
    const groupDominantsBySector = (productDirectory as unknown as {
      groupDominantsBySector: (value: DominantContractItem[]) => Array<{ id: string; items: DominantContractItem[] }>
    }).groupDominantsBySector

    assert.deepEqual(groupDominantsBySector(items), [
      { id: 'black', items: [items[1]] },
      { id: 'nonferrous', items: [items[3]] },
      { id: 'precious', items: [items[4], items[0]] },
      { id: 'other', items: [items[2]] },
    ])
  })
})
