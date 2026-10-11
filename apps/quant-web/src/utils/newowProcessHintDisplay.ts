import type { NewowProductChartBar, NewowProductHintMarker } from '../components/market/detail/newow/newowProductChartPrimitives.ts'

const appearances: Readonly<Record<string, { text: string; color: string; below: boolean; cycle?: boolean }>> = {
  'MAGIC11:4高': { text: '4高', color: '#4CAF50', below: false, cycle: true },
  'MAGIC11:7低': { text: '7低', color: '#F5A623', below: true, cycle: true },
  'MAGIC11:11变': { text: '11变', color: '#E91E63', below: false, cycle: true },
  'MAGIC11:4低': { text: '4低', color: '#E53935', below: true, cycle: true },
  'MAGIC11:7高': { text: '7高', color: '#4CAF50', below: false, cycle: true },
  J: { text: 'J', color: '#00FF00', below: false },
  D4: { text: '★B', color: '#E53935', below: true },
  D5: { text: '★B', color: '#4CAF50', below: true },
  D6: { text: '★B', color: '#2979FF', below: true },
  NEWOW_ESCAPE_D1: { text: '★S逃命', color: '#E53935', below: false },
  NEWOW_ESCAPE_D2: { text: '★S逃', color: '#4CAF50', below: false },
  NEWOW_ESCAPE_D3: { text: '★S跑', color: '#2979FF', below: false },
}

/** Display placement only: signal kind, timing and ownership always come from the server. */
export function newowProcessHintDisplay(hint: NewowProductHintMarker, bar: NewowProductChartBar) {
  const appearance = appearances[hint.kind]
  if (!appearance || hint.anchorPrice === null || !Number.isFinite(hint.value)
    || hint.barEnd !== bar.barEnd || hint.physicalContract !== bar.physicalContract
    || hint.segmentId !== bar.segmentId || hint.sourceIdentity !== bar.sourceIdentity) return null
  return {
    ...appearance,
    // Niuwa positions low text at LOW * .99; this never changes the reference price.
    displayPrice: appearance.below ? bar.low * .99 : bar.high,
    padding: appearance.cycle ? 5 : 3,
  }
}
