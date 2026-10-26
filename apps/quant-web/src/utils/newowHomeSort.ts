import { homePeriodDisplay, homeReferenceDisplay, homeTrendDisplay, type CardDelivery, type HomeStrategy } from './newowHomeCards.ts'
import { comparePositiveDecimalText } from './marketDisplay.ts'
import type { MarketHomeSort, MarketHomeSortDirection } from './marketHomeWorkspace.ts'

export type NewowHomeSort = 'target' | 'daily' | 'weekly' | 'trend'
export function isNewowHomeSort(sort: MarketHomeSort): sort is NewowHomeSort {
  return sort === 'target' || sort === 'daily' || sort === 'weekly' || sort === 'trend'
}

/** Sort only the displayed projection, without fetching or deriving strategy facts. */
export function sortNewowHomeRows<T extends { symbol: string }>(rows: readonly T[], deliveries: Record<string, CardDelivery>, strategy: HomeStrategy, sort: NewowHomeSort, direction: MarketHomeSortDirection): T[] {
  const value = (row: T): string | number | null => {
    const delivery = deliveries[row.symbol]
    const day = delivery?.card?.strategies[strategy]?.['1d']
    if (sort === 'target') {
      const reference = homeReferenceDisplay(day)
      const raw = reference.label === '目标' ? day?.target : reference.label === '吸筹' ? day?.absorb : null
      return reference.text !== '--' && comparePositiveDecimalText(raw, raw) !== null ? raw! : null
    }
    if (sort === 'trend') {
      const tone = homeTrendDisplay(delivery?.card?.strategies.trend['1d'], delivery).tone
      return tone === 'up' ? 1 : tone === 'down' ? 0 : null
    }
    const tone = homePeriodDisplay(sort === 'daily' ? day : delivery?.card?.strategies[strategy]?.['1w']).tone
    return ({ build: 3, hold: 2, clear: 1, flat: 0 } as Record<string, number>)[tone] ?? null
  }
  return rows.map((row, index) => ({row, index, value: value(row)})).sort((a, b) => {
    if (a.value === null || b.value === null) return a.value === b.value ? a.index - b.index : a.value === null ? 1 : -1
    const compared = typeof a.value === 'string' && typeof b.value === 'string'
      ? comparePositiveDecimalText(a.value, b.value)!
      : Number(a.value) - Number(b.value)
    return (direction === 'desc' ? -compared : compared) || a.index - b.index
  }).map(item => item.row)
}
