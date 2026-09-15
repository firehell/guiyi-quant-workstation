import type { KlineReferenceCallout } from '../types/referenceCallout.ts'

export const REFERENCE_CALLOUT_BOX = Object.freeze({ width: 96, height: 38 })
export const REFERENCE_CALLOUT_COMPACT = Object.freeze({ width: 28, height: 28 })
const REFERENCE_CALLOUT_MICRO = Object.freeze({ width: 8, height: 8 })

export interface ProjectedCallout {
  callout: KlineReferenceCallout
  x: number
  y: number
  boxWidth?: number
  boxHeight?: number
  expanded?: boolean
}
export interface PositionedCallout extends ProjectedCallout {
  left: number
  top: number
  width: number
  height: number
  compact: boolean
  lineX: number
  lineY: number
}

interface Rectangle { left: number; top: number; width: number; height: number }
const MARGIN = 2
const GAP = 2

/** Pure display layout; prices, times, identities and action counts are never changed. */
export function layoutReferenceCallouts(
  points: readonly ProjectedCallout[],
  width: number,
  height: number,
): PositionedCallout[] {
  if (!Number.isFinite(width) || !Number.isFinite(height) || width <= MARGIN * 2 || height <= MARGIN * 2) return []
  const visible = points.filter(point => point.x >= 0 && point.x <= width && point.y >= 0 && point.y <= height)
  const ordered = [...visible].sort((left, right) => Number(right.expanded === true) - Number(left.expanded === true)
    || left.x - right.x || left.y - right.y || left.callout.id.localeCompare(right.callout.id))
  const placed: PositionedCallout[] = []
  const fullArea = REFERENCE_CALLOUT_BOX.width * REFERENCE_CALLOUT_BOX.height
  const fullBudget = Math.max(1, Math.floor(width * height / (fullArea * 3)))
  const forceMicro = visible.length > placementCapacity(width, height, REFERENCE_CALLOUT_COMPACT)
  let fullCount = 0

  for (const point of ordered) {
    const requestedWidth = boundedDimension(point.boxWidth, REFERENCE_CALLOUT_BOX.width)
    const requestedHeight = boundedDimension(point.boxHeight, REFERENCE_CALLOUT_BOX.height)
    const canFitFull = requestedWidth <= width - MARGIN * 2 && requestedHeight <= height - MARGIN * 2
    const shouldTryFull = canFitFull && (point.expanded === true || fullCount < fullBudget)
    const full = shouldTryFull
      ? findPlacement(point, requestedWidth, requestedHeight, width, height, placed)
      : null
    const compact = full === null
    const rectangle = full ?? compactPlacement(point, width, height, placed, forceMicro)
    // Micro nodes are the final passive display fallback when labels cannot fit.
    if (rectangle === null) continue
    if (!compact) fullCount += 1
    const line = lineEndpoint(point.x, point.y, rectangle)
    placed.push({ ...point, ...rectangle, compact, lineX: line.x, lineY: line.y })
  }
  return placed.sort((left, right) => left.x - right.x || left.y - right.y || left.callout.id.localeCompare(right.callout.id))
}

function compactPlacement(
  point: ProjectedCallout,
  width: number,
  height: number,
  placed: readonly Rectangle[],
  forceMicro: boolean,
): Rectangle | null {
  const sizes = forceMicro ? [REFERENCE_CALLOUT_MICRO] : [REFERENCE_CALLOUT_COMPACT, REFERENCE_CALLOUT_MICRO]
  for (const size of sizes) {
    if (size.width > width - MARGIN * 2 || size.height > height - MARGIN * 2) continue
    const rectangle = findPlacement(point, size.width, size.height, width, height, placed)
    if (rectangle !== null) return rectangle
  }
  return null
}

function placementCapacity(width: number, height: number, size: Readonly<{ width: number; height: number }>): number {
  const columns = Math.max(0, Math.floor((width - MARGIN * 2 + GAP) / (size.width + GAP)))
  const rows = Math.max(0, Math.floor((height - MARGIN * 2 + GAP) / (size.height + GAP)))
  return columns * rows
}

function findPlacement(
  point: ProjectedCallout,
  boxWidth: number,
  boxHeight: number,
  areaWidth: number,
  areaHeight: number,
  placed: readonly Rectangle[],
): Rectangle | null {
  const preferredTop = point.callout.above ? point.y - boxHeight - 22 : point.y + 18
  const candidates: Rectangle[] = []
  for (let top = MARGIN; top <= areaHeight - boxHeight - MARGIN; top += boxHeight + GAP) {
    for (let left = MARGIN; left <= areaWidth - boxWidth - MARGIN; left += boxWidth + GAP) {
      candidates.push({ left, top, width: boxWidth, height: boxHeight })
    }
  }
  candidates.push({
    left: clamp(point.x - boxWidth / 2, MARGIN, areaWidth - boxWidth - MARGIN),
    top: clamp(preferredTop, MARGIN, areaHeight - boxHeight - MARGIN),
    width: boxWidth,
    height: boxHeight,
  })
  candidates.sort((left, right) => candidateDistance(left, point, preferredTop) - candidateDistance(right, point, preferredTop)
    || left.top - right.top || left.left - right.left)
  return candidates.find(candidate => placed.every(other => !overlaps(candidate, other))) ?? null
}

function candidateDistance(rectangle: Rectangle, point: ProjectedCallout, preferredTop: number): number {
  const centerX = rectangle.left + rectangle.width / 2
  return Math.abs(centerX - point.x) * 2 + Math.abs(rectangle.top - preferredTop)
}

function overlaps(left: Rectangle, right: Rectangle): boolean {
  return left.left < right.left + right.width + GAP
    && left.left + left.width + GAP > right.left
    && left.top < right.top + right.height + GAP
    && left.top + left.height + GAP > right.top
}

function lineEndpoint(x: number, y: number, rectangle: Rectangle): { x: number; y: number } {
  const nearestX = clamp(x, rectangle.left, rectangle.left + rectangle.width)
  const nearestY = clamp(y, rectangle.top, rectangle.top + rectangle.height)
  if (x < rectangle.left || x > rectangle.left + rectangle.width || y < rectangle.top || y > rectangle.top + rectangle.height) {
    return { x: nearestX, y: nearestY }
  }
  const edges = [
    { x, y: rectangle.top, distance: y - rectangle.top },
    { x, y: rectangle.top + rectangle.height, distance: rectangle.top + rectangle.height - y },
    { x: rectangle.left, y, distance: x - rectangle.left },
    { x: rectangle.left + rectangle.width, y, distance: rectangle.left + rectangle.width - x },
  ]
  return edges.sort((left, right) => left.distance - right.distance)[0]!
}

function boundedDimension(value: number | undefined, fallback: number): number {
  return Number.isFinite(value) && value! > 0 ? Math.ceil(value!) : fallback
}

function clamp(value: number, minimum: number, maximum: number): number {
  return Math.min(maximum, Math.max(minimum, value))
}

export function matchesReferenceBar(callout: Pick<KlineReferenceCallout, 'time' | 'physicalContract'>, bar: { time: string; physicalContract?: string }): boolean { return bar.physicalContract === callout.physicalContract && Date.parse(bar.time) === Date.parse(callout.time) }
