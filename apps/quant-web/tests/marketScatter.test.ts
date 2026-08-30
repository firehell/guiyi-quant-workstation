import assert from 'node:assert/strict'
import test from 'node:test'

import type { MarketRadarItem, MarketRadarResponse } from '../src/types/market.ts'

function item(
  symbol: string,
  priceChange: number | null,
  oiChange: number | null,
): MarketRadarItem {
  return {
    symbol,
    product_name: symbol.toUpperCase(),
    sector: 'black',
    price_change_1d: priceChange,
    price_change_5d: null,
    volume_ratio20: null,
    oi_change_1d: oiChange,
    atr14_percentile252: null,
    position20: null,
    turnover: null,
    reason_codes: [],
  }
}

test('groups each complete radar item into one signed quadrant and keeps zero changes neutral', async () => {
  const module = await import('../src/utils/marketScatter.ts').catch(() => null)
  assert.ok(module, 'market scatter grouping helper must exist')

  const groups = module.groupMarketScatterItems([
    item('down-build', -0.02, 0.01),
    item('up-build', 0.02, 0.01),
    item('down-reduce', -0.02, -0.01),
    item('up-reduce', 0.02, -0.01),
    item('flat-price', 0, 0.01),
    item('flat-oi', 0.01, 0),
    item('flat-both', 0, 0),
    item('missing-price', null, 0.01),
    item('missing-oi', 0.01, null),
  ])

  assert.deepEqual(groups.map((group) => [group.key, group.items.map((entry) => entry.symbol)]), [
    ['down_increase', ['down-build']],
    ['up_increase', ['up-build']],
    ['down_decrease', ['down-reduce']],
    ['up_decrease', ['up-reduce']],
    ['neutral', ['flat-oi', 'flat-price', 'flat-both']],
  ])
  assert.equal(groups.flatMap((group) => group.items).length, 7)
})

test('sorts each quadrant by combined absolute change and breaks ties by symbol', async () => {
  const module = await import('../src/utils/marketScatter.ts').catch(() => null)
  assert.ok(module, 'market scatter grouping helper must exist')

  const groups = module.groupMarketScatterItems([
    item('beta', 0.02, 0.02),
    item('minor', 0.01, 0.01),
    item('gamma', 0.03, 0.02),
    item('alpha', 0.02, 0.02),
  ])

  const upIncrease = groups.find((group) => group.key === 'up_increase')
  assert.deepEqual(upIncrease?.items.map((entry) => entry.symbol), ['gamma', 'alpha', 'beta', 'minor'])
})

test('normalizes an attention-free Radar payload through the public API path', async () => {
  const module = await import('../src/types/market.ts')
  const payload = {
    status: 'ready',
    expected_as_of: '2026-08-25',
    target_as_of: '2026-08-25',
    data_as_of: '2026-08-25',
    freshness_state: 'current',
    freshness_message: '当前完整',
    active_count: 1,
    participant_count: 1,
    stale: [],
    unavailable: [],
    summary: {
      up_count: 1,
      down_count: 0,
      volume_expansion_count: 1,
      oi_increase_count: 1,
      high_volatility_count: 0,
    },
    items: [{
      ...item('jm', '0.012' as unknown as number, '-0.021' as unknown as number),
      volume_ratio20: '1.5' as unknown as number,
      turnover: '1000.25' as unknown as number,
    }],
    sector_summary: [{
      sector: 'black',
      total_count: 1,
      participant_count: 1,
      up_count: 1,
      down_count: 0,
      median_price_change_1d: '0.012' as unknown as number,
    }],
  } as MarketRadarResponse

  assert.equal(typeof module.normalizeMarketRadar, 'function')
  const result = module.normalizeMarketRadar(payload)

  assert.equal(result.items[0].price_change_1d, 0.012)
  assert.equal(result.items[0].oi_change_1d, -0.021)
  assert.equal(result.items[0].volume_ratio20, 1.5)
  assert.equal(result.items[0].turnover, 1000.25)
  assert.equal(result.sector_summary[0].median_price_change_1d, 0.012)
})
