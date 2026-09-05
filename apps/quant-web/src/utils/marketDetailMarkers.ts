import type { KlineMarker } from '../types/market.ts'
import type { MarketDetailView } from '../types/marketDetail.ts'
import { ALERT_RULE_CODES } from './alertRules.ts'

/** Keeps strategy-owned markers out of Workspaces that have no strategy fact authority. */
export function markersForDetailView(
  view: MarketDetailView,
  markers: readonly KlineMarker[],
): KlineMarker[] {
  if (view === 'free' || view === 'trend') return []
  if (view === 'htdy') return markers.filter((marker) => marker.alertRuleCode === ALERT_RULE_CODES.HTDY)
  if (view === 'subing') return markers.filter((marker) => marker.alertRuleCode === ALERT_RULE_CODES.SUBING_THS)
  return []
}
