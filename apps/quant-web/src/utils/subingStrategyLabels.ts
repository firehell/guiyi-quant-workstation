import type { KlineMarker } from '../types/market.ts'

export interface SubingStrategyLabelAnchor {
  id: string
  label: string
  x: number
  wickY: number
  preferredSide: 'above' | 'below'
  boxWidth?: number
  resultTone?: 'profit' | 'loss' | null
}

export interface SubingStrategyLabelLayout {
  id: string
  label: string
  title: string
  detail: string
  left: number
  top: number
  width: number
  height: number
  side: 'above' | 'below'
  leaderFromY: number
  leaderToY: number
  resultTone?: 'profit' | 'loss' | null
}

export function splitSubingStrategyChartLabel(label: string): { title: string; detail: string } {
  const newline = label.indexOf('\n')
  if (newline < 0) return { title: label, detail: '' }
  return {
    title: label.slice(0, newline),
    detail: label.slice(newline + 1),
  }
}

/** Approximate pixel width for 11px Chinese UI labels (padding and 1px border included). */
export function estimateSubingLabelBoxWidth(label: string): number {
  let maxContent = 0
  for (const line of label.split('\n')) {
    let content = 0
    for (const char of line) {
      content += /[\u3400-\u9FFF\uF900-\uFAFF\uFF00-\uFFEF]/.test(char) ? 11 : 6.5
    }
    maxContent = Math.max(maxContent, content)
  }
  return Math.max(32, Math.ceil(maxContent + 12))
}

export function isSubingStrategyMarker(marker: Pick<KlineMarker, 'id'>): boolean {
  return marker.id.startsWith('historical:')
}

export function preferredSideFromMarker(
  marker: Pick<KlineMarker, 'position'>,
): 'above' | 'below' {
  return marker.position === 'belowBar' ? 'below' : 'above'
}

export function layoutSubingStrategyLabels(
  anchors: readonly SubingStrategyLabelAnchor[],
  options: {
    pane: { left: number; top: number; width: number; height: number }
    boxWidth?: number
    boxHeight: number
    gap: number
    stackGap: number
    clusterX?: number
  },
): SubingStrategyLabelLayout[] {
  const { pane, boxHeight, gap, stackGap } = options
  const usable = anchors.filter((anchor) => (
    Number.isFinite(anchor.x) && Number.isFinite(anchor.wickY)
  ))
  if (!usable.length) return []

  const withWidth = usable.map((anchor) => ({
    ...anchor,
    boxWidth: anchor.boxWidth
      ?? options.boxWidth
      ?? estimateSubingLabelBoxWidth(anchor.label),
  }))
  const clusterX = options.clusterX
    ?? Math.max(...withWidth.map((anchor) => anchor.boxWidth))

  const sorted = [...withWidth].sort((left, right) => (
    left.x - right.x || left.id.localeCompare(right.id)
  ))
  const clusters: typeof withWidth[] = []
  for (const anchor of sorted) {
    const current = clusters.at(-1)
    const lastX = current?.at(-1)?.x
    if (!current || lastX === undefined || Math.abs(anchor.x - lastX) > clusterX) {
      clusters.push([anchor])
      continue
    }
    current.push(anchor)
  }

  const layouts: SubingStrategyLabelLayout[] = []
  for (const cluster of clusters) {
    const preferred = majoritySide(cluster)
    layouts.push(...placeCluster(cluster, preferred, {
      pane, boxHeight, gap, stackGap,
    }))
  }
  return layouts.sort((left, right) => left.id.localeCompare(right.id))
}

function majoritySide(cluster: readonly SubingStrategyLabelAnchor[]): 'above' | 'below' {
  let above = 0
  let below = 0
  for (const anchor of cluster) {
    if (anchor.preferredSide === 'above') above += 1
    else below += 1
  }
  return below > above ? 'below' : 'above'
}

function placeCluster(
  cluster: readonly (SubingStrategyLabelAnchor & { boxWidth: number })[],
  side: 'above' | 'below',
  options: {
    pane: { left: number; top: number; width: number; height: number }
    boxHeight: number
    gap: number
    stackGap: number
  },
): SubingStrategyLabelLayout[] {
  const keep = (items: readonly SubingStrategyLabelLayout[]) => (
    items.filter((item) => shouldKeepLabel(item, options.pane))
  )
  const attempt = layoutClusterOnSide(cluster, side, options)
  if (attempt.every((item) => fitsPaneVertically(item, options.pane))) return keep(attempt)
  const flipped: 'above' | 'below' = side === 'above' ? 'below' : 'above'
  const second = layoutClusterOnSide(cluster, flipped, options)
  if (second.every((item) => fitsPaneVertically(item, options.pane))) return keep(second)
  return keep(attempt)
}

function layoutClusterOnSide(
  cluster: readonly (SubingStrategyLabelAnchor & { boxWidth: number })[],
  side: 'above' | 'below',
  options: {
    boxHeight: number
    gap: number
    stackGap: number
  },
): SubingStrategyLabelLayout[] {
  const { boxHeight, gap, stackGap } = options
  const ordered = side === 'above'
    ? [...cluster].sort((left, right) => left.wickY - right.wickY || left.id.localeCompare(right.id))
    : [...cluster].sort((left, right) => right.wickY - left.wickY || left.id.localeCompare(right.id))
  const wickY = side === 'above'
    ? Math.min(...cluster.map((item) => item.wickY))
    : Math.max(...cluster.map((item) => item.wickY))
  const x = cluster.reduce((sum, item) => sum + item.x, 0) / cluster.length
  const result: SubingStrategyLabelLayout[] = []
  for (let index = 0; index < ordered.length; index += 1) {
    const anchor = ordered[index]
    const width = anchor.boxWidth
    const offset = index * (boxHeight + stackGap)
    const top = side === 'above'
      ? wickY - gap - boxHeight - offset
      : wickY + gap + offset
    const nearEdge = side === 'above' ? top + boxHeight : top
    result.push({
      id: anchor.id,
      label: anchor.label,
      ...splitSubingStrategyChartLabel(anchor.label),
      left: x - width / 2,
      top,
      width,
      height: boxHeight,
      side,
      leaderFromY: wickY,
      leaderToY: nearEdge,
      resultTone: anchor.resultTone ?? null,
    })
  }
  return result
}

function fitsPaneVertically(
  item: SubingStrategyLabelLayout,
  pane: { top: number; height: number },
): boolean {
  if (!Number.isFinite(item.top) || !Number.isFinite(item.height)) return false
  return item.top >= pane.top && item.top + item.height <= pane.top + pane.height
}

function isFullyOutsideHorizontally(
  item: SubingStrategyLabelLayout,
  pane: { left: number; width: number },
): boolean {
  if (!Number.isFinite(item.left) || !Number.isFinite(item.width)) return true
  return item.left + item.width <= pane.left || item.left >= pane.left + pane.width
}

function shouldKeepLabel(
  item: SubingStrategyLabelLayout,
  pane: { left: number; top: number; width: number; height: number },
): boolean {
  if (isFullyOutsideHorizontally(item, pane)) return false
  return fitsPaneVertically(item, pane)
}
