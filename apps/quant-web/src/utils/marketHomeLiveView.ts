import type { MarketHomeLiveItem } from '../types/market.ts'

export type MarketHomeLiveDisplayRow<T> = T & { liveQuote: MarketHomeLiveItem | null }

export function projectMarketHomeLiveRows<T extends { symbol: string; actual_contract: string; close: number; price_change_1d: number | null }>(
  rows: readonly T[],
  liveItems: ReadonlyMap<string, MarketHomeLiveItem>,
): Array<MarketHomeLiveDisplayRow<T>> {
  return rows.map((row) => {
    const item = liveItems.get(row.symbol)
    const matches = item?.physicalContract?.toUpperCase() === row.actual_contract.toUpperCase()
      && item.price !== null && item.source !== 'none' && item.availability !== 'unavailable'
    if (!item || !matches) return { ...row, liveQuote: null }
    return { ...row, close: item.price, price_change_1d: item.priceChange, liveQuote: item }
  })
}
