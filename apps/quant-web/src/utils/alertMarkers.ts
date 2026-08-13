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
      const observations = new Set(event.observation_types)
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
  const merged = new Map<string, KlineMarker>()
  for (const marker of [...currentObservationMarkers, ...persistentAlertMarkers]) {
    merged.set(marker.id, marker)
  }
  return [...merged.values()]
}
