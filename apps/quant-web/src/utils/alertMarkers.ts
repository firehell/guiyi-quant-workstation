import type { AlertEvent, KlineMarker, MarketFrequency, SeriesKind } from '../types/market.ts'
import {
  ALERT_RULE_PRESENTATIONS,
  alertDirectionalTone,
  alertResultLabel,
  getAlertRulePresentation,
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
): string[] {
  if (seriesKind !== 'actual_dominant') return []
  return ALERT_RULE_PRESENTATIONS
    .filter((presentation) => presentation.persistentFrequencies.includes(frequency))
    .map((presentation) => presentation.ruleCode)
}

export function alertEventsToMarkers(events: AlertEvent[]): KlineMarker[] {
  return [...events]
    .sort((left, right) => Date.parse(left.bar_end) - Date.parse(right.bar_end))
    .flatMap((event) => {
      if (event.rule_code !== 'htdy_original_15m') return []
      const observations = event.result_codes.filter(
        (item): item is 'buy' | 'sell' => item === 'buy' || item === 'sell',
      )
      const label = alertResultLabel(event.rule_code, observations)
      if (label === '提醒记录') return []
      return [{
        id: `alert:${event.rule_code}:${event.symbol}:${event.frequency}:${event.bar_end}`,
        time: event.bar_end,
        label,
        tooltip: `持久 AlertEvent · ${event.contract} · ${label}`,
        tone: markerTone(event.rule_code, observations),
        position: 'aboveBar' as const,
        shape: 'square' as const,
      }]
    })
}

function markerTone(
  ruleCode: string,
  observations: AlertEvent['result_codes'],
): KlineMarker['tone'] {
  const presentation = getAlertRulePresentation(ruleCode)
  if (presentation?.markerTone) return presentation.markerTone
  const direction = alertDirectionalTone(
    ruleCode,
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
