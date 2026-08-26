import type {
  IPrimitivePaneRenderer,
  IPrimitivePaneView,
  ISeriesPrimitive,
  PrimitiveHoveredItem,
  SeriesAttachedParameter,
  Time,
  UTCTimestamp,
} from 'lightweight-charts'
import type { NStructureBand } from '../../types/market.ts'

const LABEL_MIN_WIDTH = 28
const OVERLAP_GROUP_MIN_SIZE = 3
const OVERLAP_RATIO_THRESHOLD = 0.6
const OVERLAP_GROUP_MAX_HOPS = 3
const HOVER_TOLERANCE = 3
const EXTERNAL_ID_PREFIX = 'n-structure-band:'
const GROUP_EXTERNAL_ID_PREFIX = 'n-structure-band-group:'
export const N_STRUCTURE_BAND_RENDER_CONTRACT = {
  zOrder: 'normal',
  drawLayer: 'background',
} as const

export interface NStructureBandGeometry {
  band: NStructureBand
  x1: number
  visibleX1: number
  completionX: number
  x2: number
  visibleX2: number
  top: number
  visibleTop: number
  bottom: number
  visibleBottom: number
  completionY: number
  reentryX: number | null
  reentryY: number | null
  invalidationX: number | null
  invalidationY: number | null
  clippedLeft: boolean
  completionVisible: boolean
  labelVisible: boolean
  labelX: number
  labelY: number
  overlapGroupId: string | null
  overlapCount: number
  overlapPosition: number
  overlapLabel: string
  isOverlapPrimary: boolean
  isOverlapSuppressed: boolean
  overlapGroupAllInvalidated: boolean
}

type CoordinateResolver = (value: string) => number | null
type PriceCoordinateResolver = (value: number) => number | null
export interface NStructureBandPalette { up: string; down: string }
interface ViewportBounds { left: number; right: number; top?: number; bottom?: number }
const DEFAULT_PALETTE: NStructureBandPalette = { up: '#dc2626', down: '#16a34a' }

export function bandVisualStyle(
  direction: NStructureBand['direction'],
  palette: NStructureBandPalette = DEFAULT_PALETTE,
) {
  return {
    fillAlpha: 0.06,
    expansionFillAlpha: 0.025,
    strokeAlpha: 0.55,
    solid: direction === 'up' ? palette.up : palette.down,
  }
}

export function buildNStructureBandGeometry(
  bands: readonly NStructureBand[],
  loadedStart: string,
  timeToCoordinate: CoordinateResolver,
  priceToCoordinate: PriceCoordinateResolver,
  viewport?: ViewportBounds,
  selectedBandByGroup: ReadonlyMap<string, string> = new Map(),
): NStructureBandGeometry[] {
  const loadedStartMs = Date.parse(loadedStart)
  const geometry = [...bands]
    .sort((left, right) => Date.parse(left.completed_at) - Date.parse(right.completed_at))
    .flatMap((band) => {
      const n1Ms = Date.parse(band.n1_at)
      const completedMs = Date.parse(band.completed_at)
      const expandedMs = Date.parse(band.expanded_until)
      if (Number.isFinite(loadedStartMs) && Number.isFinite(expandedMs) && expandedMs < loadedStartMs) {
        return []
      }
      const clippedLeft = Number.isFinite(loadedStartMs)
        && Number.isFinite(n1Ms)
        && n1Ms < loadedStartMs
      const completionVisible = !(
        Number.isFinite(loadedStartMs)
        && Number.isFinite(completedMs)
        && completedMs < loadedStartMs
      )
      const x1 = timeToCoordinate(clippedLeft ? loadedStart : band.n1_at)
      const completionX = completionVisible ? timeToCoordinate(band.completed_at) : x1
      const expandedX = timeToCoordinate(band.expanded_until)
      const lowerY = priceToCoordinate(band.lower)
      const upperY = priceToCoordinate(band.upper)
      const completionY = priceToCoordinate(band.completion_level)
      if ([x1, completionX, expandedX, lowerY, upperY, completionY].some((value) => value === null || !Number.isFinite(value))) {
        return []
      }
      const left = Math.min(x1!, completionX!)
      const right = Math.max(completionX!, expandedX!)
      if (viewport && (right < viewport.left || left > viewport.right)) return []
      const top = Math.min(lowerY!, upperY!)
      const bottom = Math.max(lowerY!, upperY!)
      const visibleX1 = viewport ? Math.max(left, viewport.left) : left
      const visibleX2 = viewport ? Math.min(right, viewport.right) : right
      const visibleTop = viewport?.top === undefined ? top : Math.max(top, viewport.top)
      const visibleBottom = viewport?.bottom === undefined ? bottom : Math.min(bottom, viewport.bottom)
      if (visibleX2 <= visibleX1 || visibleBottom <= visibleTop) return []
      const reentryX = !eventIsVisible(band.first_reentered_at, loadedStartMs)
        ? null
        : timeToCoordinate(band.first_reentered_at!)
      const invalidationX = !eventIsVisible(band.invalidated_at, loadedStartMs)
        ? null
        : timeToCoordinate(band.invalidated_at!)
      return [{
        band,
        x1: left,
        visibleX1,
        completionX: completionX!,
        x2: right,
        visibleX2,
        top,
        visibleTop,
        bottom,
        visibleBottom,
        completionY: completionY!,
        reentryX: reentryX !== null && Number.isFinite(reentryX) ? reentryX : null,
        reentryY: band.first_reentered_at === null
          ? null
          : band.direction === 'up' ? upperY! : lowerY!,
        invalidationX: invalidationX !== null && Number.isFinite(invalidationX) ? invalidationX : null,
        invalidationY: band.invalidated_at === null
          ? null
          : band.direction === 'up' ? lowerY! : upperY!,
        clippedLeft,
        completionVisible,
        labelVisible: completionVisible && completionX! - left >= LABEL_MIN_WIDTH,
        labelX: visibleX1 + 6,
        labelY: visibleTop + 5,
        overlapGroupId: null,
        overlapCount: 1,
        overlapPosition: 1,
        overlapLabel: band.direction === 'up' ? 'N↑' : 'N↓',
        isOverlapPrimary: true,
        isOverlapSuppressed: false,
        overlapGroupAllInvalidated: band.invalidated_at !== null,
      }]
    })
  return groupNStructureBandGeometry(geometry, selectedBandByGroup)
}

export function nextNStructureBandGroupSelection(
  geometry: readonly NStructureBandGeometry[],
  groupId: string,
): string | null {
  const members = geometry
    .filter((item) => item.overlapGroupId === groupId)
    .sort((left, right) => left.overlapPosition - right.overlapPosition)
  if (members.length < OVERLAP_GROUP_MIN_SIZE) return null
  const selectedIndex = members.findIndex((item) => item.isOverlapPrimary)
  return members[(selectedIndex + 1) % members.length]?.band.band_id ?? null
}

export function nStructureBandRenderStyle(item: NStructureBandGeometry) {
  const isDenseGroup = item.overlapCount >= OVERLAP_GROUP_MIN_SIZE
  const opacityMultiplier = isDenseGroup && item.overlapGroupAllInvalidated ? 0.65 : 1
  return {
    drawFullBand: !item.isOverlapSuppressed,
    drawEvents: !item.isOverlapSuppressed,
    railAlpha: item.isOverlapSuppressed ? 0.15 * opacityMultiplier : 0,
    opacityMultiplier,
    label: item.isOverlapSuppressed ? '' : item.overlapLabel,
  }
}

export function hitNStructureBandOverlapLabel(
  geometry: readonly NStructureBandGeometry[],
  x: number,
  y: number,
): NStructureBandGeometry | null {
  return geometry.find((item) => {
    if (
      item.overlapCount < OVERLAP_GROUP_MIN_SIZE
      || !item.isOverlapPrimary
      || !item.labelVisible
      || !item.overlapGroupId
    ) return false
    const labelLeft = item.labelX - 2
    const labelTop = item.labelY - 2
    const labelWidth = Math.max(36, item.overlapLabel.length * 7 + 8)
    return labelLeft <= x && x <= labelLeft + labelWidth && labelTop <= y && y <= labelTop + 16
  }) ?? null
}

function groupNStructureBandGeometry(
  geometry: readonly NStructureBandGeometry[],
  selectedBandByGroup: ReadonlyMap<string, string>,
): NStructureBandGeometry[] {
  const grouped = geometry.map((item) => ({ ...item }))
  for (const direction of ['up', 'down'] as const) {
    const remaining = grouped
      .filter((item) => item.band.direction === direction)
      .sort(compareOverlapPriority)
    while (remaining.length) {
      const anchor = remaining.shift()!
      const members = priorityAnchorOverlapGroup(anchor, remaining)
      if (members.length < OVERLAP_GROUP_MIN_SIZE) continue
      const memberIds = new Set(members.map((item) => item.band.band_id))
      for (let index = remaining.length - 1; index >= 0; index -= 1) {
        if (memberIds.has(remaining[index]!.band.band_id)) remaining.splice(index, 1)
      }
      const priority = [...members].sort(compareOverlapPriority)
      const groupId = `${direction}:${priority.map((item) => item.band.band_id).sort().join('|')}`
      const requestedSelection = selectedBandByGroup.get(groupId)
      const selected = priority.find((item) => item.band.band_id === requestedSelection) ?? priority[0]!
      const allInvalidated = priority.every((item) => item.band.invalidated_at !== null)
      const groupLabelX = Math.max(...priority.map((item) => item.visibleX1)) + 6
      const groupLabelY = Math.max(...priority.map((item) => item.visibleTop)) + 5
      for (const item of priority) {
        const position = priority.findIndex((candidate) => candidate.band.band_id === item.band.band_id) + 1
        const isPrimary = item.band.band_id === selected.band.band_id
        item.overlapGroupId = groupId
        item.overlapCount = priority.length
        item.overlapPosition = position
        item.overlapLabel = isPrimary
          ? `${direction === 'up' ? 'N↑' : 'N↓'} ${position === 1 ? `×${priority.length}` : `${position}/${priority.length}`}`
          : ''
        item.isOverlapPrimary = isPrimary
        item.isOverlapSuppressed = !isPrimary
        item.overlapGroupAllInvalidated = allInvalidated
        item.labelX = groupLabelX
        item.labelY = groupLabelY
        if (isPrimary) {
          item.labelVisible = true
        }
      }
    }
  }
  return grouped.sort((left, right) => {
    if (left.isOverlapSuppressed !== right.isOverlapSuppressed) return left.isOverlapSuppressed ? -1 : 1
    return Date.parse(left.band.completed_at) - Date.parse(right.band.completed_at)
  })
}

function priorityAnchorOverlapGroup(
  anchor: NStructureBandGeometry,
  candidates: readonly NStructureBandGeometry[],
): NStructureBandGeometry[] {
  const members = [anchor]
  let frontier = [anchor]
  let unseen = [...candidates]
  for (let hop = 1; hop <= OVERLAP_GROUP_MAX_HOPS && frontier.length; hop += 1) {
    const connected = unseen.filter((candidate) => (
      frontier.some((member) => overlapRatio(member, candidate) >= OVERLAP_RATIO_THRESHOLD)
    ))
    if (!connected.length) break
    const connectedIds = new Set(connected.map((item) => item.band.band_id))
    members.push(...connected)
    unseen = unseen.filter((item) => !connectedIds.has(item.band.band_id))
    frontier = connected
  }
  return members
}

function compareOverlapPriority(left: NStructureBandGeometry, right: NStructureBandGeometry): number {
  const activeDifference = Number(right.band.invalidated_at === null) - Number(left.band.invalidated_at === null)
  if (activeDifference !== 0) return activeDifference
  const completionDifference = Date.parse(right.band.completed_at) - Date.parse(left.band.completed_at)
  return completionDifference || left.band.band_id.localeCompare(right.band.band_id)
}

function overlapRatio(left: NStructureBandGeometry, right: NStructureBandGeometry): number {
  const intersectionWidth = Math.max(0, Math.min(left.visibleX2, right.visibleX2) - Math.max(left.visibleX1, right.visibleX1))
  const intersectionHeight = Math.max(0, Math.min(left.visibleBottom, right.visibleBottom) - Math.max(left.visibleTop, right.visibleTop))
  if (intersectionWidth === 0 || intersectionHeight === 0) return 0
  const leftArea = Math.max(1, left.visibleX2 - left.visibleX1) * Math.max(1, left.visibleBottom - left.visibleTop)
  const rightArea = Math.max(1, right.visibleX2 - right.visibleX1) * Math.max(1, right.visibleBottom - right.visibleTop)
  return intersectionWidth * intersectionHeight / Math.min(leftArea, rightArea)
}

export function hitNStructureBandGeometry(
  geometry: readonly NStructureBandGeometry[],
  x: number,
  y: number,
): NStructureBandGeometry | null {
  const hits = geometry.filter((item) => (
    item.x1 - HOVER_TOLERANCE <= x
    && x <= item.x2 + HOVER_TOLERANCE
    && item.top - HOVER_TOLERANCE <= y
    && y <= item.bottom + HOVER_TOLERANCE
  ))
  const visibleHits = hits.some((item) => !item.isOverlapSuppressed)
    ? hits.filter((item) => !item.isOverlapSuppressed)
    : hits
  return visibleHits.sort(
    (left, right) => Date.parse(right.band.completed_at) - Date.parse(left.band.completed_at),
  )[0] ?? null
}

class NStructureBandRenderer implements IPrimitivePaneRenderer {
  private readonly primitive: NStructureBandPrimitive

  constructor(primitive: NStructureBandPrimitive) {
    this.primitive = primitive
  }

  draw(): void {}

  drawBackground(target: Parameters<IPrimitivePaneRenderer['draw']>[0]): void {
    target.useMediaCoordinateSpace(({ context }) => {
      context.save()
      context.lineWidth = 1
      context.font = '600 11px -apple-system, BlinkMacSystemFont, sans-serif'
      context.textBaseline = 'top'
      for (const item of this.primitive.currentGeometry()) {
        const style = this.primitive.visualStyle(item.band.direction)
        const renderStyle = nStructureBandRenderStyle(item)
        const height = Math.max(1, item.bottom - item.top)
        if (!renderStyle.drawFullBand) {
          context.beginPath()
          context.strokeStyle = style.solid
          context.globalAlpha = renderStyle.railAlpha
          context.setLineDash([3, 4])
          context.moveTo(item.x1, item.top + 0.5)
          context.lineTo(item.x2, item.top + 0.5)
          context.moveTo(item.x1, item.bottom - 0.5)
          context.lineTo(item.x2, item.bottom - 0.5)
          context.stroke()
          context.setLineDash([])
          continue
        }
        const formationWidth = Math.max(0, item.completionX - item.x1)
        if (formationWidth > 0) {
          context.fillStyle = style.solid
          context.globalAlpha = style.fillAlpha * renderStyle.opacityMultiplier
          context.fillRect(item.x1, item.top, formationWidth, height)
          context.strokeStyle = style.solid
          context.globalAlpha = style.strokeAlpha * renderStyle.opacityMultiplier
          context.setLineDash([])
          context.strokeRect(item.x1 + 0.5, item.top + 0.5, Math.max(0, formationWidth - 1), Math.max(0, height - 1))
        }
        const expansionWidth = Math.max(0, item.x2 - item.completionX)
        if (expansionWidth > 0) {
          context.fillStyle = style.solid
          context.globalAlpha = style.expansionFillAlpha * renderStyle.opacityMultiplier
          context.fillRect(item.completionX, item.top, expansionWidth, height)
          context.strokeStyle = style.solid
          context.globalAlpha = style.strokeAlpha * renderStyle.opacityMultiplier
          context.setLineDash([4, 3])
          context.strokeRect(item.completionX + 0.5, item.top + 0.5, Math.max(0, expansionWidth - 1), Math.max(0, height - 1))
          context.setLineDash([])
        }
        if (renderStyle.drawEvents && item.completionVisible) {
          context.beginPath()
          context.fillStyle = style.solid
          context.globalAlpha = renderStyle.opacityMultiplier
          context.arc(item.completionX, item.completionY, 3, 0, Math.PI * 2)
          context.fill()
        }
        if (renderStyle.drawEvents && item.reentryX !== null && item.reentryY !== null) {
          context.beginPath()
          context.strokeStyle = style.solid
          context.globalAlpha = renderStyle.opacityMultiplier
          context.lineWidth = 1.5
          context.arc(item.reentryX, item.reentryY, 3.5, 0, Math.PI * 2)
          context.stroke()
          context.lineWidth = 1
        }
        if (renderStyle.drawEvents && item.invalidationX !== null && item.invalidationY !== null) {
          const size = 4
          context.beginPath()
          context.strokeStyle = style.solid
          context.globalAlpha = renderStyle.opacityMultiplier
          context.lineWidth = 1.5
          context.moveTo(item.invalidationX - size, item.invalidationY - size)
          context.lineTo(item.invalidationX + size, item.invalidationY + size)
          context.moveTo(item.invalidationX + size, item.invalidationY - size)
          context.lineTo(item.invalidationX - size, item.invalidationY + size)
          context.stroke()
          context.lineWidth = 1
        }
        if (item.labelVisible && renderStyle.label && item.overlapCount < OVERLAP_GROUP_MIN_SIZE) {
          context.fillStyle = style.solid
          context.globalAlpha = renderStyle.opacityMultiplier
          context.fillText(renderStyle.label, item.labelX, item.labelY)
        }
      }
      context.restore()
    })
  }
}

class NStructureBandPaneView implements IPrimitivePaneView {
  private readonly paneRenderer: NStructureBandRenderer

  constructor(primitive: NStructureBandPrimitive) {
    this.paneRenderer = new NStructureBandRenderer(primitive)
  }

  zOrder(): 'normal' { return N_STRUCTURE_BAND_RENDER_CONTRACT.zOrder }
  renderer(): IPrimitivePaneRenderer { return this.paneRenderer }
}

export class NStructureBandPrimitive implements ISeriesPrimitive<Time> {
  private readonly view = new NStructureBandPaneView(this)
  private readonly palette: NStructureBandPalette
  private readonly onGeometryChange?: () => void
  private attachedParameters: SeriesAttachedParameter<Time> | null = null
  private bands: readonly NStructureBand[] = []
  private loadedStart = ''
  private geometry: NStructureBandGeometry[] = []
  private readonly selectedBandByGroup = new Map<string, string>()
  private selectionGeometrySignature: string | null = null

  constructor(
    palette: NStructureBandPalette = DEFAULT_PALETTE,
    onGeometryChange?: () => void,
  ) {
    this.palette = palette
    this.onGeometryChange = onGeometryChange
  }

  attached(parameters: SeriesAttachedParameter<Time>): void {
    this.attachedParameters = parameters
    this.updateAllViews()
  }

  detached(): void {
    this.attachedParameters = null
    this.geometry = []
  }

  paneViews(): readonly IPrimitivePaneView[] { return [this.view] }

  updateAllViews(): void {
    const parameters = this.attachedParameters
    if (!parameters) return
    const paneHeight = (parameters.chart as unknown as {
      panes?: () => Array<{ getHeight?: () => number }>
    }).panes?.()[0]?.getHeight?.()
    const build = () => buildNStructureBandGeometry(
      this.bands,
      this.loadedStart,
      (value) => parameters.chart.timeScale().timeToCoordinate(toChartTime(value)),
      (value) => parameters.series.priceToCoordinate(value),
      {
        left: 0,
        right: parameters.chart.timeScale().width(),
        top: 0,
        bottom: Number.isFinite(paneHeight) ? paneHeight : undefined,
      },
      this.selectedBandByGroup,
    )
    this.geometry = build()
    const currentSignature = geometryCoordinateSignature(this.geometry)
    if (
      this.selectedBandByGroup.size
      && this.selectionGeometrySignature !== null
      && currentSignature !== this.selectionGeometrySignature
    ) {
      this.selectedBandByGroup.clear()
      this.selectionGeometrySignature = null
      this.geometry = build()
    }
    this.onGeometryChange?.()
  }

  setData(bands: readonly NStructureBand[], loadedStart: string): void {
    this.selectedBandByGroup.clear()
    this.selectionGeometrySignature = null
    this.bands = bands
    this.loadedStart = loadedStart
    this.updateAllViews()
    this.attachedParameters?.requestUpdate()
  }

  currentGeometry(): readonly NStructureBandGeometry[] { return this.geometry }

  visualStyle(direction: NStructureBand['direction']) {
    return bandVisualStyle(direction, this.palette)
  }

  hitTest(x: number, y: number): PrimitiveHoveredItem | null {
    const labelHit = hitNStructureBandOverlapLabel(this.geometry, x, y)
    if (labelHit?.overlapGroupId) return {
      externalId: `${GROUP_EXTERNAL_ID_PREFIX}${labelHit.overlapGroupId}`,
      zOrder: N_STRUCTURE_BAND_RENDER_CONTRACT.zOrder,
      isBackground: true,
      itemType: 'primitive',
      cursorStyle: 'pointer',
      hitTestPriority: 1,
      distance: 0,
    }
    const hit = hitNStructureBandGeometry(this.geometry, x, y)
    return hit ? {
      externalId: `${EXTERNAL_ID_PREFIX}${hit.band.band_id}`,
      zOrder: N_STRUCTURE_BAND_RENDER_CONTRACT.zOrder,
      isBackground: true,
      itemType: 'primitive',
      cursorStyle: 'help',
      hitTestPriority: 0,
      distance: 0,
    } : null
  }

  bandByExternalId(externalId: string | undefined): NStructureBand | null {
    if (externalId?.startsWith(GROUP_EXTERNAL_ID_PREFIX)) {
      const groupId = externalId.slice(GROUP_EXTERNAL_ID_PREFIX.length)
      return this.geometry.find((item) => (
        item.overlapGroupId === groupId && item.isOverlapPrimary
      ))?.band ?? null
    }
    if (!externalId?.startsWith(EXTERNAL_ID_PREFIX)) return null
    const bandId = externalId.slice(EXTERNAL_ID_PREFIX.length)
    return this.bands.find((band) => band.band_id === bandId) ?? null
  }

  overlapInfoByExternalId(externalId: string | undefined): { groupId: string; count: number; position: number } | null {
    const band = this.bandByExternalId(externalId)
    if (!band) return null
    const item = this.geometry.find((candidate) => candidate.band.band_id === band.band_id)
    return item?.overlapGroupId && item.overlapCount > 1
      ? { groupId: item.overlapGroupId, count: item.overlapCount, position: item.overlapPosition }
      : null
  }

  cycleOverlapGroupByExternalId(externalId: string | undefined): boolean {
    if (!externalId?.startsWith(GROUP_EXTERNAL_ID_PREFIX)) return false
    const groupId = externalId.slice(GROUP_EXTERNAL_ID_PREFIX.length)
    const nextBandId = nextNStructureBandGroupSelection(this.geometry, groupId)
    if (!nextBandId) return false
    this.selectionGeometrySignature = geometryCoordinateSignature(this.geometry)
    this.selectedBandByGroup.set(groupId, nextBandId)
    this.updateAllViews()
    this.attachedParameters?.requestUpdate()
    return true
  }

  resetOverlapSelection(): boolean {
    if (!this.selectedBandByGroup.size) return false
    this.selectedBandByGroup.clear()
    this.selectionGeometrySignature = null
    this.updateAllViews()
    this.attachedParameters?.requestUpdate()
    return true
  }
}

function geometryCoordinateSignature(geometry: readonly NStructureBandGeometry[]): string {
  return [...geometry].sort((left, right) => left.band.band_id.localeCompare(right.band.band_id)).map((item) => [
    item.band.band_id,
    item.x1,
    item.completionX,
    item.x2,
    item.top,
    item.bottom,
    item.overlapGroupId,
  ].join(':')).join('|')
}

function toChartTime(value: string): UTCTimestamp {
  return Math.floor(Date.parse(value) / 1000) as UTCTimestamp
}

function eventIsVisible(value: string | null, loadedStartMs: number): boolean {
  if (value === null) return false
  const valueMs = Date.parse(value)
  return Number.isFinite(valueMs)
    && (!Number.isFinite(loadedStartMs) || valueMs >= loadedStartMs)
}
