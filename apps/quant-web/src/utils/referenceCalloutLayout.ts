import type { KlineReferenceCallout } from '../types/referenceCallout.ts'
export interface ProjectedCallout { callout: KlineReferenceCallout; x: number; y: number }
export interface PositionedCallout extends ProjectedCallout { left: number; top: number; compact: boolean }
/** Layout only: all prices and returns remain server facts. */
export function layoutReferenceCallouts(points: ProjectedCallout[], width: number, height: number): PositionedCallout[] {
  const placed: PositionedCallout[] = []
  for (const point of [...points].sort((a, b) => a.x - b.x)) {
    if (point.x < 0 || point.x > width || point.y < 0 || point.y > height) continue
    const left = Math.min(Math.max(2, point.x - 66), Math.max(2, width - 134))
    let top = Math.max(48, Math.min(height - 48, point.y + (point.callout.above ? -78 : 32)))
    let compact = width < 260
    const overlaps = () => placed.some((other) => !other.compact && left < other.left + 134 && left + 134 > other.left && top < other.top + 46 && top + 46 > other.top)
    for (let lane = 0; overlaps() && lane < 3; lane++) top += point.callout.above ? -48 : 48
    if (top < 48 || top > height - 48 || overlaps()) compact = true
    placed.push({ ...point, left: compact ? Math.min(width - 24, Math.max(0, point.x - 12)) : left, top: compact ? Math.max(48, Math.min(height - 26, point.y + (point.callout.above ? -28 : 8))) : top, compact })
  }
  return placed
}

export function matchesReferenceBar(callout: Pick<KlineReferenceCallout, 'time' | 'physicalContract'>, bar: { time: string; physicalContract?: string }): boolean { return bar.physicalContract === callout.physicalContract && Date.parse(bar.time) === Date.parse(callout.time) }
