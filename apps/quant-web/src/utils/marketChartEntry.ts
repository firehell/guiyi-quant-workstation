import type { MarketFrequency, SeriesKind } from '@/types/market'

export function seriesRefreshQuery(input: {
  symbol: string
  contract: string
  seriesKind: SeriesKind
  frequency: MarketFrequency
}): Record<string, string | undefined> {
  return {
    symbol: input.symbol,
    contract: input.seriesKind === 'contract' && input.contract ? input.contract : undefined,
    series_kind: input.seriesKind,
    frequency: input.frequency,
  }
}
