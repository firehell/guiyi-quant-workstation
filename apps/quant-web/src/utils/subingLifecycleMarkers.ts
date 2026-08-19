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
    addTransitionMarker(markers, snapshot, 'setup_armed', '准备')
  }
  if (snapshot.trigger_kind === 'pivot_break') {
    addMarker(markers, key, 'pivot-break', snapshot.triggered_at, snapshot.direction === 'short' ? '前低突破' : '前高突破')
  }
  if (snapshot.confirmed_at) {
    addMarker(markers, key, 'entry', snapshot.confirmed_at, '研究确认')
  }
  if (snapshot.stage === 'exit_risk') {
    addTransitionMarker(markers, snapshot, 'exit_risk', '风险')
  }
  if (snapshot.stage === 'closed') {
    addTransitionMarker(markers, snapshot, 'closed', '结束')
  }
  return markers.sort((left, right) => Date.parse(left.time) - Date.parse(right.time) || left.id.localeCompare(right.id))
}

function addTransitionMarker(
  markers: KlineMarker[],
  snapshot: SubingLifecycleSnapshot,
  target: 'setup_armed' | 'exit_risk' | 'closed',
  label: string,
): void {
  const transition = snapshot.latest_transition
  if (!transition || transition.to_stage !== target || !snapshot.opportunity_key) return
  addMarker(
    markers,
    snapshot.opportunity_key,
    `transition:${transition.transition_id}`,
    transition.transition_at,
    label,
  )
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
