import { alertEventsToMarkers } from './alertMarkers.ts'
import { isHtdyAlertEvent, isSubingThsAlertEvent } from './alertRules.ts'
import type { AlertEvent, BarData, KlineMarker } from '../types/market.ts'
export interface OwnedSignalMarker {
  strategy: string; frequency: string; barEnd: string; physicalContract: string
  formulaVersion?: string
  source: 'historical_replay' | 'actual_observation'; marker: KlineMarker
}
function key(signal: OwnedSignalMarker): string {
  return [signal.strategy, signal.frequency, Date.parse(signal.barEnd), signal.physicalContract.toUpperCase()].join('|')
}
/** Formal history displays Canonical replay only; first-seen events belong to audit. */
export function canonicalHistoryMarkers(historical: readonly OwnedSignalMarker[], identity: { strategy: string; frequency: string }): KlineMarker[] {
  const unique = new Map<string, OwnedSignalMarker>()
  for (const item of historical) {
    if (item.source === 'historical_replay' && item.strategy === identity.strategy && item.frequency === identity.frequency
      && Number.isFinite(Date.parse(item.barEnd)) && Boolean(item.physicalContract)) unique.set(`${key(item)}|${item.marker.id}`, item)
  }
  return [...unique.values()].sort((a, b) => Date.parse(a.barEnd) - Date.parse(b.barEnd)).map(item => item.marker)
}

/** Physical ownership comes exclusively from the event and the loaded authoritative bar. */
export function actualEventsToOwnedMarkers(events: readonly AlertEvent[], bars: readonly BarData[], identity: { symbol: string; strategy: string; frequency: string }): OwnedSignalMarker[] {
  return events.filter(event => event.symbol.toLowerCase() === identity.symbol.toLowerCase() && event.frequency === identity.frequency
    && (identity.strategy === 'htdy' ? isHtdyAlertEvent(event) : identity.strategy === 'subing' && isSubingThsAlertEvent(event))
    && bars.some(bar => Date.parse(bar.time) === Date.parse(event.bar_end) && bar.physicalContract?.toUpperCase() === event.contract.toUpperCase()))
    .flatMap(event => alertEventsToMarkers([event]).map(marker => ({ strategy: identity.strategy, frequency: event.frequency,
      formulaVersion: 'formula_version' in event ? event.formula_version ?? undefined : undefined,
      barEnd: event.bar_end, physicalContract: event.contract, source: 'actual_observation' as const, marker: { ...marker, tooltip: `${marker.tooltip ?? '实际观察'} · 公式版本 ${'formula_version' in event && event.formula_version ? event.formula_version : '未记录'}` } })))
}
