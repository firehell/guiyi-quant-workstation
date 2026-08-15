import type { AlertEvent, KlineMarker, MarketFrequency, SeriesKind } from '../types/market.ts'


export function isPersistentAlertIdentity(
  seriesKind: SeriesKind,
  frequency: MarketFrequency,
): boolean {
  return seriesKind === 'actual_dominant' && frequency === '15m'
}

export function alertEventsToMarkers(events: AlertEvent[]): KlineMarker[] {
  return [...events]
    .sort((left, right) => Date.parse(left.bar_end) - Date.parse(right.bar_end))
    .flatMap((event) => {
      const observations = new Set(event.result_codes)
      const label = observations.has('buy') && observations.has('sell')
        ? '🔔买/卖'
        : observations.has('buy') ? '🔔买' : observations.has('sell') ? '🔔卖' : null
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
