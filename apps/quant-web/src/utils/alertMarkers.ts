import type { AlertEvent, KlineMarker, MarketFrequency, SeriesKind } from '../types/market.ts'

const SUBING_RULE_CODE = 'subing_entry_signal_v1'
const HTDY_RULE_CODE = 'htdy_original_15m'

export function isPersistentAlertIdentity(
  seriesKind: SeriesKind,
  frequency: MarketFrequency,
): boolean {
  return markerRuleCodes(seriesKind, frequency).length > 0
}

export function markerRuleCodes(
  seriesKind: SeriesKind,
  frequency: MarketFrequency,
): string[] {
  if (seriesKind !== 'actual_dominant') return []
  if (frequency === '5m') return [SUBING_RULE_CODE]
  if (frequency === '15m') return [HTDY_RULE_CODE, SUBING_RULE_CODE]
  return []
}

export function alertEventsToMarkers(events: AlertEvent[]): KlineMarker[] {
  return [...events]
    .sort((left, right) => Date.parse(left.bar_end) - Date.parse(right.bar_end))
    .flatMap((event) => {
      const observations = new Set(event.result_codes)
      const label = markerLabel(event.rule_code, observations)
      if (!label) return []
      return [{
        id: `alert:${event.rule_code}:${event.symbol}:${event.bar_end}`,
        time: event.bar_end,
        label,
        tooltip: `持久 AlertEvent · ${event.contract} · ${label}`,
        color: '#facc15',
        position: 'aboveBar' as const,
        shape: 'square' as const,
      }]
    })
}

function markerLabel(ruleCode: string, observations: Set<'buy' | 'sell'>): string | null {
  const category = ruleCode === SUBING_RULE_CODE
    ? '信号'
    : ruleCode === HTDY_RULE_CODE ? '观察' : null
  if (!category) return null
  if (observations.has('buy')) return `买入${category}`
  if (observations.has('sell')) return `卖出${category}`
  return null
}

export function mergeKlineMarkers(
  currentObservationMarkers: KlineMarker[],
  persistentAlertMarkers: KlineMarker[],
): KlineMarker[] {
  const merged = new Map<string, { marker: KlineMarker; sourceOrder: number }>()
  for (const [sourceOrder, markers] of [currentObservationMarkers, persistentAlertMarkers].entries()) {
    for (const marker of markers) merged.set(marker.id, { marker, sourceOrder })
  }
  return [...merged.values()]
    .sort((left, right) => {
      const timeOrder = Date.parse(left.marker.time) - Date.parse(right.marker.time)
      return timeOrder
        || left.sourceOrder - right.sourceOrder
        || left.marker.id.localeCompare(right.marker.id)
    })
    .map(({ marker }) => marker)
}
