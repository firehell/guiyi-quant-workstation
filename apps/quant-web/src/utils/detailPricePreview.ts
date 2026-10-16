import { normalizeMarketBarsPageResponse } from '../api/marketWire.ts'
import type { MarketBarsPageRequest, MarketBarsPageResponse } from '../types/market.ts'

/** Disposable storage is checked before rendering, never used as strategy proof. */
export function validateDetailPrice(value: unknown, query: MarketBarsPageRequest): MarketBarsPageResponse {
  const page = normalizeMarketBarsPageResponse(value)
  if (page.request?.symbol !== query.symbol || page.request.frequency !== query.frequency
    || page.request.series_kind !== query.series_kind || page.request.contract !== (query.contract ?? null)
    || page.request.before !== (query.before ?? null) || page.request.limit !== (query.limit ?? 500)
    || !Array.isArray(page.resolved_contract_segments) || page.bars.length > (query.limit ?? 500)) throw new Error('PRICE_IDENTITY_INVALID')
  let previous = -Infinity
  for (const bar of page.bars) {
    const end = Date.parse(bar.bar_end)
    if (!Number.isFinite(end) || end <= previous || !/^\d{4}-\d{2}-\d{2}$/.test(bar.trading_day)
      || ![bar.open, bar.high, bar.low, bar.close].every(price => price > 0)
      || bar.low > Math.min(bar.open, bar.close) || bar.high < Math.max(bar.open, bar.close)
      || (query.series_kind === 'actual_dominant' && !page.resolved_contract_segments.some(segment =>
        typeof segment.contract === 'string' && segment.start_trading_day <= bar.trading_day && segment.end_trading_day >= bar.trading_day))) throw new Error('PRICE_PREVIEW_INVALID')
    previous = end
  }
  return page
}
