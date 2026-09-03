import type { KlineMarker } from '../types/market.ts'
import type { MarketDetailView } from '../types/marketDetail.ts'

/** Keeps strategy-owned markers out of Workspaces that have no strategy fact authority. */
export function markersForDetailView(
  view: MarketDetailView,
  markers: readonly KlineMarker[],
): KlineMarker[] {
  if (view === 'free' || view === 'trend') return []
  return [...markers]
}
