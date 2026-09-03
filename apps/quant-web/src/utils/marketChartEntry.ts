import type { MarketFrequency, SeriesKind } from '../types/market.ts'

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

export function resolveFocusBarEnd(
  value: unknown,
  identity: { seriesKind: SeriesKind; frequency: MarketFrequency },
): string | null {
  if (identity.seriesKind !== 'actual_dominant' || identity.frequency !== '15m') return null
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}T.*(?:Z|[+-]\d{2}:?\d{2})$/.test(value)) return null
  const day = value.slice(0, 10)
  const dayValue = new Date(`${day}T00:00:00Z`)
  if (!Number.isFinite(dayValue.getTime()) || dayValue.toISOString().slice(0, 10) !== day) return null
  return Number.isFinite(Date.parse(value)) ? value : null
}

export function withoutFocusBarEnd<T extends Record<string, unknown>>(
  query: T,
): Omit<T, 'focus_bar_end'> {
  const { focus_bar_end: _focusBarEnd, ...remaining } = query
  return remaining
}

export function consumeFocusBarEnd(
  value: string,
  identity: { seriesKind: SeriesKind; frequency: MarketFrequency },
  reveal: (focusBarEnd: string) => boolean,
): boolean {
  const focusBarEnd = resolveFocusBarEnd(value, identity)
  if (focusBarEnd === null) return false
  reveal(focusBarEnd)
  return true
}
