import type { MarketDetailIdentity } from '../types/marketDetail.ts'

/** T-menu route changes keep product identity and clear stale comparison/focus. */
export function newowMenuIdentity(identity: MarketDetailIdentity, strategy: 'main_rise' | 'oscillation'): MarketDetailIdentity {
  return {
    view: 'newow',
    symbol: identity.symbol,
    strategy,
    seriesKind: 'actual_dominant',
    frequency: strategy === 'main_rise' && !['1d', '1w', '60m'].includes(identity.frequency) ? '1d' : identity.frequency,
  }
}
