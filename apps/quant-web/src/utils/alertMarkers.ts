import type {
  AlertEvent,
  KlineMarker,
  MarketFrequency,
  ResearchOverlayId,
  SeriesKind,
} from '../types/market.ts'
import {
  ALERT_RULE_PRESENTATIONS,
  ALERT_RULE_CODES,
  type AlertRuleCode,
  alertEventDirectionalTone,
  alertEventIdentityKey,
  alertEventMarkerTone,
  alertEventResultLabel,
  alertEventRuleCode,
  isHtdyAlertEvent,
  isSubingThsAlertEvent,
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
    .flatMap<KlineMarker>((event): KlineMarker[] => {
      if (isSubingThsAlertEvent(event)) {
        const direction = event.result_codes[0]
        const rising = direction === 'buy'
        return [{
          id: `alert:${alertEventIdentityKey(event)}`,
          time: event.bar_end,
          label: rising ? 'S↑' : 'S↓',
          tooltip: [
            '苏冰预警',
            rising ? 'MACD 金叉' : 'MACD 死叉',
            rising ? '收盘价位于 EMA21 上方' : '收盘价位于 EMA21 下方',
            event.contract,
            `信号K线 ${shanghaiHm(event.bar_end)}`,
          ].join(' · '),
          tone: rising ? 'up' : 'down',
          position: rising ? 'belowBar' as const : 'aboveBar' as const,
          shape: rising ? 'arrowUp' as const : 'arrowDown' as const,
          alertRuleCode: alertEventRuleCode(event),
        }]
      }
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
        tooltip: [
          '实时首次识别',
          '持久 AlertEvent',
          event.contract,
          label,
          `观察K线 ${shanghaiHm(event.bar_end)}`,
          `首次识别 ${shanghaiHm(event.detected_at)}`,
        ].join(' · '),
        tone: markerTone(event, observations),
        position: 'aboveBar' as const,
        shape: 'square' as const,
        alertRuleCode: alertEventRuleCode(event),
      }]
    })
}

function shanghaiHm(value: string): string {
  return new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai',
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
  }).format(new Date(value))
}

export function alertMarkersForOverlay(
  overlay: ResearchOverlayId,
  markers: readonly KlineMarker[],
): KlineMarker[] {
  return markers.filter((marker) => (
    marker.alertRuleCode === ALERT_RULE_CODES.SUBING_THS
    || (overlay === 'htdy' && marker.alertRuleCode === ALERT_RULE_CODES.HTDY)
  ))
}

function markerTone(
  event: AlertEvent,
  observations: AlertEvent['result_codes'],
): KlineMarker['tone'] {
  const registeredTone = alertEventMarkerTone(event)
  if (registeredTone === 'htdy') return registeredTone
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
