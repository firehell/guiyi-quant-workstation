import assert from 'node:assert/strict'
import test from 'node:test'
import { selectMarketFocus } from '../src/utils/marketFocus.ts'
import type { MarketRadarItem } from '../src/types/market.ts'

function item(
  symbol: string,
  reasonCodes: string[],
  overrides: Partial<MarketRadarItem> = {},
): MarketRadarItem {
  return {
    symbol,
    product_name: symbol.toUpperCase(),
    sector: 'black',
    price_change_1d: 0.01,
    price_change_5d: 0.02,
    volume_ratio20: 1.2,
    oi_change_1d: 0.01,
    atr14_percentile252: 0.5,
    position20: 0.5,
    turnover: 1000,
    reason_codes: reasonCodes,
    ...overrides,
  }
}

test('focus requires EMA direction plus at least one participation fact', () => {
  assert.deepEqual(selectMarketFocus([
    item('a', ['ema21_up']),
    item('b', ['ema21_up', 'near_20d_high']),
    item('c', ['ema21_up', 'high_volatility']),
    item('d', ['ema21_up', 'oi_increase']),
    item('e', ['ema21_down', 'price_move_down']),
  ]).map((entry) => [entry.item.symbol, entry.direction]), [
    ['d', 'long'],
    ['e', 'short'],
  ])
})

test('focus uses transparent tuple ordering and caps output at three', () => {
  const result = selectMarketFocus([
    item('a', ['ema21_up', 'price_move_up'], { turnover: 5000 }),
    item('b', ['ema21_up', 'price_move_up', 'volume_expansion'], { turnover: 1000 }),
    item('c', ['ema21_down', 'price_move_down', 'oi_increase'], { turnover: 900 }),
    item('d', ['ema21_up', 'price_move_up', 'volume_expansion', 'oi_increase'], { turnover: 100 }),
  ])

  assert.deepEqual(result.map((entry) => entry.item.symbol), ['d', 'c', 'b'])
})

test('focus projects one risk with oi decrease before high volatility', () => {
  const [result] = selectMarketFocus([
    item('a', ['ema21_up', 'price_move_up', 'oi_decrease', 'high_volatility']),
  ])

  assert.equal(result.riskLabel, '减仓推动')
})

test('focus breaks an otherwise equal tie by turnover then symbol without mutating input', () => {
  const reasonCodes = ['ema21_up', 'price_move_up']
  const items = [
    item('c', [...reasonCodes], { turnover: null }),
    item('b', [...reasonCodes], { turnover: 2000 }),
    item('a', [...reasonCodes], { turnover: 2000 }),
  ]
  const originalItems = [...items]
  const originalReasons = items.map((entry) => [...entry.reason_codes])

  assert.deepEqual(selectMarketFocus(items).map((entry) => entry.item.symbol), ['a', 'b', 'c'])
  assert.deepEqual(items, originalItems)
  assert.deepEqual(items.map((entry) => entry.reason_codes), originalReasons)
})

test('focus permits zero qualified items', () => {
  assert.deepEqual(selectMarketFocus([
    item('a', ['near_20d_low', 'oi_decrease']),
    item('b', ['ema21_down', 'high_volatility']),
  ]), [])
})
