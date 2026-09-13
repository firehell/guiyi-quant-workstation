import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

import { normalizeProductOptions, searchProductOptions } from '../src/utils/productSearch.ts'

const options = normalizeProductOptions([
  { product: 'au', product_name: '黄金', actual_contract: 'AU2612' },
  { product: 'rb', product_name: '螺纹钢', actual_contract: 'RB2701' },
  { product: 'i', product_name: '铁矿石', actual_contract: 'I2701' },
])

test('searches the complete directory by Chinese name or product code', () => {
  assert.deepEqual(searchProductOptions(options, '黄').map((item) => item.symbol), ['au'])
  assert.deepEqual(searchProductOptions(options, 'RB').map((item) => item.symbol), ['rb'])
  assert.deepEqual(searchProductOptions(options, '矿 石').map((item) => item.symbol), ['i'])
  assert.equal(searchProductOptions(options, '铜').length, 0)
})

test('normalizes duplicate directory rows without requiring a quote', () => {
  const normalized = normalizeProductOptions([
    { product: 'AU', product_name: '黄金', actual_contract: 'AU2612' },
    { product: 'au', product_name: '重复', actual_contract: null },
    { product: '', product_name: '无效', actual_contract: null },
  ])
  assert.deepEqual(normalized, [{ symbol: 'au', name: '黄金', contract: 'AU2612' }])
})

test('ProductSelector exposes combobox keyboard and explicit empty/error states', () => {
  const source = readFileSync(new URL('../src/components/market/ProductSelector.vue', import.meta.url), 'utf8')
  assert.match(source, /role="combobox"/)
  assert.match(source, /aria-activedescendant/)
  assert.match(source, /@keydown\.down\.prevent/)
  assert.match(source, /@keydown\.up\.prevent/)
  assert.match(source, /@keydown\.enter\.prevent/)
  assert.match(source, /@keydown\.esc\.prevent/)
  assert.match(source, /目录加载失败/)
  assert.match(source, /没有匹配品种/)
  assert.match(source, /previousFocus|inputRef\.value\?\.focus/)
})
