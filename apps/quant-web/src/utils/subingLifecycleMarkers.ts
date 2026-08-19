import type { KlineMarker, SubingLifecycleSnapshot } from '../types/market.ts'

/**
 * Project the immutable current lifecycle snapshot into deliberately neutral
 * research markers. These are not persistent AlertEvent markers.
 */
export function lifecycleSnapshotToMarkers(snapshot: SubingLifecycleSnapshot): KlineMarker[] {
  if (snapshot.availability !== 'ready' || !snapshot.research_only || !snapshot.opportunity_key) return []

  const markers: KlineMarker[] = []
  const key = snapshot.opportunity_key
  if (snapshot.stage === 'setup_armed') {
    addMarker(markers, key, 'setup', snapshot.latest_transition?.transition_at ?? snapshot.observed_at, '准备')
  }
  if (snapshot.trigger_kind === 'pivot_break') {
    addMarker(markers, key, 'pivot-break', snapshot.triggered_at, snapshot.direction === 'short' ? '前低突破' : '前高突破')
  }
  if (snapshot.confirmed_at) {
    addMarker(markers, key, 'entry', snapshot.confirmed_at, '研究确认')
  }
  if (snapshot.stage === 'exit_risk') {
    addMarker(markers, key, 'exit-risk', snapshot.latest_transition?.transition_at ?? snapshot.observed_at, '风险')
  }
  if (snapshot.stage === 'closed') {
    addMarker(markers, key, 'closed', snapshot.latest_transition?.transition_at ?? snapshot.observed_at, '结束')
  }
  return markers.sort((left, right) => Date.parse(left.time) - Date.parse(right.time) || left.id.localeCompare(right.id))
}

function addMarker(
  markers: KlineMarker[],
  key: string,
  fact: string,
  time: string | null,
  label: string,
): void {
  if (!time || !Number.isFinite(Date.parse(time))) return
  markers.push({
    id: `lifecycle:${key}:${fact}`,
    time,
    label,
    tooltip: `SuBing 生命周期研究 · ${label}`,
    tone: 'neutral',
    position: 'belowBar',
    shape: 'circle',
  })
}
