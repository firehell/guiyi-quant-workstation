import type { AlertEvent, KlineMarker, MarketFrequency, SeriesKind } from '../types/market.ts'
import {
  ALERT_RULE_PRESENTATIONS,
  type AlertRuleCode,
  alertEventDirectionalTone,
  alertEventIdentityKey,
  alertEventMarkerTone,
  alertEventResultLabel,
  isHtdyAlertEvent,
} from './alertRules.ts'

export function isPersistentAlertIdentity(
  seriesKind: SeriesKind,
  frequency: MarketFrequency,
): boolean {
  return markerRuleCodes(seriesKind, frequency).length > 0
}

export function markerRuleCodes(
  seriesKind: SeriesKind,
  frequency: MarketFrequency,
): AlertRuleCode[] {
  if (seriesKind !== 'actual_dominant') return []
  return ALERT_RULE_PRESENTATIONS
    .filter((presentation) => presentation.persistentFrequencies.includes(frequency))
    .map((presentation) => presentation.ruleCode)
}

export function alertEventsToMarkers(events: AlertEvent[]): KlineMarker[] {
  return [...events]
    .sort((left, right) => Date.parse(left.bar_end) - Date.parse(right.bar_end))
    .flatMap((event) => {
      if (!isHtdyAlertEvent(event)) return []
      const observations = event.result_codes.filter(
        (item): item is 'buy' | 'sell' => item === 'buy' || item === 'sell',
      )
      const label = alertEventResultLabel(event, observations)
      if (label === '提醒记录') return []
      return [{
        id: `alert:${alertEventIdentityKey(event)}`,
        time: event.bar_end,
        label,
        tooltip: `持久 AlertEvent · ${event.contract} · ${label}`,
        tone: markerTone(event, observations),
        position: 'aboveBar' as const,
        shape: 'square' as const,
      }]
    })
}

function markerTone(
  event: AlertEvent,
  observations: AlertEvent['result_codes'],
): KlineMarker['tone'] {
  const registeredTone = alertEventMarkerTone(event)
  if (registeredTone) return registeredTone
  const direction = alertEventDirectionalTone(
    event,
    observations.filter((item): item is 'buy' | 'sell' => item === 'buy' || item === 'sell'),
  )
  if (direction === 'buy') return 'up'
  if (direction === 'sell') return 'down'
  return 'neutral'
}

export function mergeKlineMarkers(
  currentObservationMarkers: KlineMarker[],
  persistentAlertMarkers: KlineMarker[],
): KlineMarker[] {
  const merged = new Map<string, { marker: KlineMarker; sourceOrder: number }>()
  for (const [sourceOrder, markers] of [currentObservationMarkers, persistentAlertMarkers].entries()) {
    for (const marker of markers) {
      const key = marker.dedupeKey ?? marker.id
      const existing = merged.get(key)
      const existingPriority = existing ? persistentPriority(existing.marker) : -1
      const nextPriority = persistentPriority(marker)
      if (!existing || nextPriority >= existingPriority) {
        merged.set(key, { marker, sourceOrder })
      }
    }
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

function persistentPriority(marker: KlineMarker): number {
  return marker.id.startsWith('alert:') ? 1 : 0
}
