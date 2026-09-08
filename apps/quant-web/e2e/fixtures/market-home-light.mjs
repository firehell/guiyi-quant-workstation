/** Controlled visual fixture; names/categories are taxonomy, prices and states are synthetic. */
import { readFileSync } from 'node:fs'

const taxonomy = readFileSync(new URL('../../../../data/universe/product_sectors.csv', import.meta.url), 'utf8')
  .trim().split(/\r?\n/).slice(1).map(line => {
    const [symbol, product_name, sector] = line.split(',')
    return { symbol, product_name, sector }
  })

export function lightHomeOverview() {
  const items = taxonomy.map((entry, index) => ({
    ...entry,
    exchange: 'TEST', actual_contract: `${entry.symbol.toUpperCase()}2611`,
    dominant_mapping_date: '2026-09-04', data_as_of: '2026-09-04',
    close: String(1100 + Math.floor(index / 2) * 123.5),
    price_change_1d: String((index % 13 - 6) / 200),
    price_change_5d: null, volume_ratio20: index % 7 === 0 ? null : (0.8 + (index % 8) / 10).toFixed(2),
    oi_change_1d: index % 9 === 0 ? null : String((index % 7 - 3) / 100),
    atr14_percentile252: null,
    daily_trend: ['up', 'down', 'neutral', 'up', 'down'][index % 5],
    weekly_trend: index % 11 === 0 ? 'unavailable' : ['up', 'down', 'neutral', 'down', 'up'][index % 5],
    reason_codes: [],
  }))
  const count = predicate => items.filter(predicate).length
  const sectors = [...new Set(taxonomy.map(item => item.sector))].map(sector => ({
    sector, active_count: count(item => item.sector === sector),
    participant_count: count(item => item.sector === sector), median_price_change_1d: null,
  }))
  return {
    status: 'ready', freshness: 'fresh', target_as_of: '2026-09-04', data_as_of: '2026-09-04',
    active_count: items.length, participant_count: items.length, stale_count: 0, unavailable_count: 0,
    items, sectors,
    summary: {
      price_up_count: count(item => item.price_change_1d !== null && Number(item.price_change_1d) > 0),
      price_down_count: count(item => item.price_change_1d !== null && Number(item.price_change_1d) < 0),
      price_flat_count: count(item => item.price_change_1d !== null && Number(item.price_change_1d) === 0),
      price_unavailable_count: 0,
      daily_up_count: count(item => item.daily_trend === 'up'),
      daily_down_count: count(item => item.daily_trend === 'down'),
      daily_neutral_count: count(item => item.daily_trend === 'neutral'), daily_unavailable_count: 0,
      aligned_up_count: count(item => item.daily_trend === 'up' && item.weekly_trend === 'up'),
      aligned_down_count: count(item => item.daily_trend === 'down' && item.weekly_trend === 'down'),
    },
  }
}

export function lightHomeOverviewWithUnavailablePrice() {
  const overview = lightHomeOverview()
  const row = overview.items.find((item) => item.symbol === 'rs')
  if (!row) throw new Error('controlled 60-product fixture must include rs')
  const previousPriceChange = Number(row.price_change_1d)
  if (previousPriceChange > 0) overview.summary.price_up_count -= 1
  else if (previousPriceChange < 0) overview.summary.price_down_count -= 1
  else overview.summary.price_flat_count -= 1
  // RS2609 has a completed target-day close; its prior completed D1 close is zero.
  row.actual_contract = 'RS2609'
  row.close = '1234.5'
  row.price_change_1d = null
  overview.summary.price_unavailable_count = 1
  return overview
}
