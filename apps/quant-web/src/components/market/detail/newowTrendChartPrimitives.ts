import type {
  IChartApi,
  IPrimitivePaneRenderer,
  IPrimitivePaneView,
  ISeriesApi,
  ISeriesPrimitive,
  SeriesAttachedParameter,
  SeriesType,
  Time,
} from 'lightweight-charts'
import type { InjectionKey } from 'vue'

import type { BarData } from '../../../types/market.ts'
import type {
  NewowCupDirection,
  NewowCupHandle,
  NewowCupState,
  NewowMarker,
  NewowMarkerType,
  NewowTrendBandState,
  NewowTrendDetailResponse,
} from '../../../types/newow.ts'

export type NewowTrendChartSource = 'newow' | 'generic-fallback'
export type NewowTrendMarkerFamily = 'trend' | 'escape' | 'cup'

export interface NewowTrendChartBar {
  readonly barEnd: string
  readonly tradingDay: string
  readonly open: number
  readonly high: number
  readonly low: number
  readonly close: number
  readonly volume: number
  readonly openInterest: number | null
  readonly physicalContract: string | null
  readonly segmentId: string | null
}

export interface NewowTrendBandLinePoint {
  readonly tradingDay: string
  readonly segmentId: string
  readonly value: number
  readonly state: NewowTrendBandState
}

export interface NewowTrendBandArea {
  readonly segmentId: string
  readonly fromTradingDay: string
  readonly throughTradingDay: string
  readonly fromB: number
  readonly fromC: number
  readonly throughB: number
  readonly throughC: number
  readonly state: Exclude<NewowTrendBandState, 'UNAVAILABLE'>
}

export interface NewowTrendChartMarker {
  readonly id: string
  readonly family: NewowTrendMarkerFamily
  readonly markerType: NewowMarkerType
  readonly tradingDay: string
  readonly label: string
  readonly position: 'aboveBar' | 'belowBar' | 'inBar'
  readonly shape: 'circle' | 'square' | 'arrowUp' | 'arrowDown'
  readonly colorRole: 'yellow' | 'blue' | 'd1' | 'd2' | 'd3' | 'cup'
}

export type NewowCupPointRole = 'left-rim' | 'bottom' | 'right-rim' | 'handle-extreme'

export interface NewowCupGeometryPoint {
  readonly role: NewowCupPointRole
  readonly tradingDay: string
  readonly price: number
}

export interface NewowCupGeometry {
  readonly candidateId: string
  readonly segmentId: string
  readonly direction: NewowCupDirection
  readonly state: NewowCupState
  readonly points: readonly NewowCupGeometryPoint[]
  readonly pivotLine: {
    readonly fromTradingDay: string
    readonly throughTradingDay: string
    readonly price: number
  } | null
}

export interface NewowRolloverProjection {
  readonly tradingDay: string
  readonly previousContract: string
  readonly nextContract: string
  readonly label: string
}

export interface NewowTrendHoverFacts {
  readonly tradingDay: string
  readonly bar: NewowTrendChartBar
  readonly physicalContract: string | null
  readonly trend: {
    readonly state: NewowTrendBandState
    readonly b: number | null
    readonly c: number | null
    readonly transition: 'BUILD' | 'CLEAR' | null
  } | null
  readonly markerLabels: readonly string[]
  readonly cupStates: readonly {
    readonly candidateId: string
    readonly direction: NewowCupDirection
    readonly state: NewowCupState
  }[]
  readonly rolloverLabel: string | null
}

export interface NewowTrendChartProjection {
  readonly source: NewowTrendChartSource
  readonly paneCount: 2
  readonly bars: readonly NewowTrendChartBar[]
  readonly band: {
    readonly b: readonly NewowTrendBandLinePoint[]
    readonly c: readonly NewowTrendBandLinePoint[]
    readonly areas: readonly NewowTrendBandArea[]
  }
  readonly markers: readonly NewowTrendChartMarker[]
  readonly cups: readonly NewowCupGeometry[]
  readonly rolloverSeams: readonly NewowRolloverProjection[]
  readonly unavailableDisclosure: string | null
  readonly hoverFacts: readonly NewowTrendHoverFacts[]
}

export interface BuildNewowTrendChartProjectionInput {
  readonly data: NewowTrendDetailResponse | null
  readonly genericBars: readonly BarData[]
}

const UNAVAILABLE_DISCLOSURE = 'Newow 趋势数据不可用，仅显示 completed D1 K 线与成交量。'
const D_PRIORITY: Readonly<Record<string, number>> = {
  NEWOW_ESCAPE_D1: 0,
  NEWOW_ESCAPE_D2: 1,
  NEWOW_ESCAPE_D3: 2,
}
const FAMILY_PRIORITY: Readonly<Record<NewowTrendMarkerFamily, number>> = {
  trend: 0,
  escape: 1,
  cup: 2,
}
const CUP_MARKER_PRIORITY: Readonly<Record<string, number>> = {
  CUP_HANDLE_READY: 0,
  CUP_HANDLE_BREAKOUT: 1,
  CUP_HANDLE_WEAKENED: 2,
  CUP_HANDLE_INVALIDATED: 3,
  CUP_HANDLE_EXPIRED: 4,
}

/** Maps already-normalized server facts to render-only data; it contains no Newow formulas. */
export function buildNewowTrendChartProjection(
  input: BuildNewowTrendChartProjectionInput,
): NewowTrendChartProjection {
  if (input.data === null) return genericFallbackProjection(input.genericBars)

  const bars = input.data.bars.map((bar): NewowTrendChartBar => ({
    barEnd: bar.bar_end,
    tradingDay: bar.trading_day,
    open: bar.open,
    high: bar.high,
    low: bar.low,
    close: bar.close,
    volume: bar.volume,
    openInterest: bar.open_interest,
    physicalContract: bar.physical_contract,
    segmentId: bar.segment_id,
  }))
  const barByBarEnd = new Map(bars.map((bar) => [bar.barEnd, bar]))
  const tradingDayByBarEnd = new Map(bars.map((bar) => [bar.barEnd, bar.tradingDay]))
  const band = projectBand(input.data, barByBarEnd)
  const markers = projectMarkers(input.data, tradingDayByBarEnd)
  const cups = projectCups(input.data.cup_handles, bars)
  const rolloverSeams = input.data.rollover_seams.map((seam): NewowRolloverProjection => ({
    tradingDay: seam.trading_day,
    previousContract: seam.previous_contract,
    nextContract: seam.next_contract,
    label: `${seam.previous_contract} → ${seam.next_contract} · 主力切换`,
  }))
  const trendByBarEnd = new Map(input.data.trend_band.map((point) => [point.bar_end, point]))
  const markersByDay = groupMarkersByTradingDay(markers)
  const cupStatesByDay = new Map<string, NewowTrendHoverFacts['cupStates']>()
  for (const cup of input.data.cup_handles) {
    const tradingDay = tradingDayByBarEnd.get(cup.state_changed_at)
    if (tradingDay === undefined) continue
    const current = cupStatesByDay.get(tradingDay) ?? []
    cupStatesByDay.set(tradingDay, [...current, {
      candidateId: cup.candidate_id, direction: cup.direction, state: cup.state,
    }])
  }
  const rolloverByDay = new Map(rolloverSeams.map((seam) => [seam.tradingDay, seam.label]))
  const hoverFacts = bars.map((bar): NewowTrendHoverFacts => {
    const trend = trendByBarEnd.get(bar.barEnd)
    return {
      tradingDay: bar.tradingDay,
      bar,
      physicalContract: bar.physicalContract,
      trend: trend === undefined ? null : {
        state: trend.state,
        b: trend.b_value,
        c: trend.c_value,
        transition: trend.transition,
      },
      markerLabels: markersByDay.get(bar.tradingDay)?.map((marker) => marker.label) ?? [],
      cupStates: cupStatesByDay.get(bar.tradingDay) ?? [],
      rolloverLabel: rolloverByDay.get(bar.tradingDay) ?? null,
    }
  })

  return {
    source: 'newow',
    paneCount: 2,
    bars,
    band,
    markers,
    cups,
    rolloverSeams,
    unavailableDisclosure: null,
    hoverFacts,
  }
}

function genericFallbackProjection(genericBars: readonly BarData[]): NewowTrendChartProjection {
  const bars = genericBars.flatMap((bar): NewowTrendChartBar[] => {
    const tradingDay = genericTradingDay(bar)
    if (tradingDay === null || !validOhlcv(bar)) return []
    return [{
      barEnd: bar.time,
      tradingDay,
      open: bar.open,
      high: bar.high,
      low: bar.low,
      close: bar.close,
      volume: bar.volume,
      openInterest: finiteOrNull(bar.openInterest),
      physicalContract: typeof bar.physicalContract === 'string' ? bar.physicalContract : null,
      segmentId: null,
    }]
  })
  return {
    source: 'generic-fallback',
    paneCount: 2,
    bars,
    band: { b: [], c: [], areas: [] },
    markers: [],
    cups: [],
    rolloverSeams: [],
    unavailableDisclosure: UNAVAILABLE_DISCLOSURE,
    hoverFacts: bars.map((bar) => ({
      tradingDay: bar.tradingDay,
      bar,
      physicalContract: bar.physicalContract,
      trend: null,
      markerLabels: [],
      cupStates: [],
      rolloverLabel: null,
    })),
  }
}

function projectBand(
  data: NewowTrendDetailResponse,
  barByBarEnd: ReadonlyMap<string, NewowTrendChartBar>,
): NewowTrendChartProjection['band'] {
  const b: NewowTrendBandLinePoint[] = []
  const c: NewowTrendBandLinePoint[] = []
  const areas: NewowTrendBandArea[] = []
  for (const point of data.trend_band) {
    const bar = barByBarEnd.get(point.bar_end)
    if (bar === undefined || bar.segmentId === null) continue
    if (point.b_value !== null) {
      b.push({ tradingDay: bar.tradingDay, segmentId: bar.segmentId, value: point.b_value, state: point.state })
    }
    if (point.c_value !== null) {
      c.push({ tradingDay: bar.tradingDay, segmentId: bar.segmentId, value: point.c_value, state: point.state })
    }
  }
  for (let index = 1; index < data.trend_band.length; index += 1) {
    const previous = data.trend_band[index - 1]!
    const current = data.trend_band[index]!
    const previousBar = barByBarEnd.get(previous.bar_end)
    const currentBar = barByBarEnd.get(current.bar_end)
    if (
      previousBar === undefined || currentBar === undefined
      || previousBar.segmentId === null || currentBar.segmentId === null
      || previousBar.segmentId !== currentBar.segmentId
      || previous.b_value === null || previous.c_value === null
      || current.b_value === null || current.c_value === null
      || current.state === 'UNAVAILABLE'
    ) continue
    areas.push({
      segmentId: currentBar.segmentId,
      fromTradingDay: previousBar.tradingDay,
      throughTradingDay: currentBar.tradingDay,
      fromB: previous.b_value,
      fromC: previous.c_value,
      throughB: current.b_value,
      throughC: current.c_value,
      state: current.state,
    })
  }
  return { b, c, areas }
}

function projectMarkers(
  data: NewowTrendDetailResponse,
  tradingDayByBarEnd: ReadonlyMap<string, string>,
): NewowTrendChartMarker[] {
  const selectedEscape = new Map<string, NewowMarker>()
  for (const marker of data.escape_markers) {
    const current = selectedEscape.get(marker.bar_end)
    if (current === undefined || dPriority(marker) < dPriority(current)) {
      selectedEscape.set(marker.bar_end, marker)
    }
  }
  const markers = [
    ...data.trend_markers.flatMap((marker) => chartMarker(marker, 'trend', tradingDayByBarEnd)),
    ...[...selectedEscape.values()].flatMap((marker) => chartMarker(marker, 'escape', tradingDayByBarEnd)),
    ...data.cup_markers.flatMap((marker) => chartMarker(marker, 'cup', tradingDayByBarEnd)),
  ]
  markers.sort((left, right) => (
    left.tradingDay.localeCompare(right.tradingDay)
    || FAMILY_PRIORITY[left.family] - FAMILY_PRIORITY[right.family]
    || markerTypePriority(left) - markerTypePriority(right)
    || left.id.localeCompare(right.id)
  ))
  return markers
}

function chartMarker(
  marker: NewowMarker,
  family: NewowTrendMarkerFamily,
  tradingDayByBarEnd: ReadonlyMap<string, string>,
): NewowTrendChartMarker[] {
  const tradingDay = tradingDayByBarEnd.get(marker.bar_end)
  if (tradingDay === undefined) return []
  if (family === 'trend') {
    const isBuild = marker.marker_type === 'BUILD'
    return [{
      id: marker.marker_id,
      family,
      markerType: marker.marker_type,
      tradingDay,
      label: isBuild ? '建仓' : '清仓',
      position: isBuild ? 'belowBar' : 'aboveBar',
      shape: isBuild ? 'arrowUp' : 'arrowDown',
      colorRole: isBuild ? 'yellow' : 'blue',
    }]
  }
  if (family === 'escape') {
    const label = marker.marker_type.replace('NEWOW_ESCAPE_', '')
    return [{
      id: marker.marker_id,
      family,
      markerType: marker.marker_type,
      tradingDay,
      label,
      position: 'aboveBar',
      shape: 'circle',
      colorRole: label.toLowerCase() as 'd1' | 'd2' | 'd3',
    }]
  }
  const isPositive = marker.marker_type === 'CUP_HANDLE_READY' || marker.marker_type === 'CUP_HANDLE_BREAKOUT'
  return [{
    id: marker.marker_id,
    family,
    markerType: marker.marker_type,
    tradingDay,
    label: marker.label,
    position: isPositive ? 'belowBar' : 'aboveBar',
    shape: isPositive ? 'square' : 'circle',
    colorRole: 'cup',
  }]
}

function projectCups(
  handles: readonly NewowCupHandle[],
  bars: readonly NewowTrendChartBar[],
): NewowCupGeometry[] {
  const firstDay = bars[0]?.tradingDay
  const lastDay = bars.at(-1)?.tradingDay
  if (firstDay === undefined || lastDay === undefined) return []
  return handles.flatMap((handle): NewowCupGeometry[] => {
    const segmentId = cupOriginSegment(handle, bars)
    if (segmentId === null) return []
    const segmentBars = bars.filter((bar) => bar.segmentId === segmentId)
    const segmentFirstDay = segmentBars[0]?.tradingDay
    const segmentLastDay = segmentBars.at(-1)?.tradingDay
    if (segmentFirstDay === undefined || segmentLastDay === undefined) return []
    const segmentDays = new Set(segmentBars.map((bar) => bar.tradingDay))
    const points = [
      cupPoint('left-rim', handle.left_rim.pivot_at, handle.left_rim.price),
      cupPoint('bottom', handle.bottom.pivot_at, handle.bottom.price),
      cupPoint('right-rim', handle.right_rim.pivot_at, handle.right_rim.price),
      handle.handle_extreme === null
        ? null
        : cupPoint('handle-extreme', handle.handle_extreme.pivot_at, handle.handle_extreme.price),
    ].filter((point): point is NewowCupGeometryPoint => (
      point !== null && segmentDays.has(point.tradingDay)
    )).sort((left, right) => left.tradingDay.localeCompare(right.tradingDay))
    const pivotStart = handle.pivot_frozen_at === null ? null : instantDay(handle.pivot_frozen_at)
    const pivotLine = handle.pivot_price !== null && pivotStart !== null
      && pivotStart <= segmentLastDay
      ? {
        fromTradingDay: pivotStart < segmentFirstDay ? segmentFirstDay : pivotStart,
        throughTradingDay: segmentLastDay,
        price: handle.pivot_price,
      }
      : null
    return points.length > 0 || pivotLine !== null
      ? [{ candidateId: handle.candidate_id, segmentId, direction: handle.direction, state: handle.state, points, pivotLine }]
      : []
  })
}

function cupOriginSegment(
  handle: NewowCupHandle,
  bars: readonly NewowTrendChartBar[],
): string | null {
  const segmentByBarEnd = new Map(bars.map((bar) => [bar.barEnd, bar.segmentId]))
  const timestamps = [
    handle.left_rim.pivot_at,
    handle.bottom.pivot_at,
    handle.right_rim.pivot_at,
    handle.handle_start_at,
    handle.handle_extreme?.pivot_at,
    handle.confirmed_at,
    handle.first_seen_at,
    handle.state_changed_at,
    handle.pivot_frozen_at,
  ].filter((value): value is string => value !== null && value !== undefined)
  for (const timestamp of timestamps) {
    const segmentId = segmentByBarEnd.get(timestamp)
    if (segmentId !== null && segmentId !== undefined) return segmentId
  }
  return null
}

function cupPoint(role: NewowCupPointRole, instant: string, price: number): NewowCupGeometryPoint | null {
  const tradingDay = instantDay(instant)
  return tradingDay === null ? null : { role, tradingDay, price }
}

function groupMarkersByTradingDay(
  markers: readonly NewowTrendChartMarker[],
): Map<string, NewowTrendChartMarker[]> {
  const grouped = new Map<string, NewowTrendChartMarker[]>()
  for (const marker of markers) {
    const current = grouped.get(marker.tradingDay) ?? []
    current.push(marker)
    grouped.set(marker.tradingDay, current)
  }
  return grouped
}

function dPriority(marker: NewowMarker): number {
  return D_PRIORITY[marker.marker_type] ?? Number.MAX_SAFE_INTEGER
}

function markerTypePriority(marker: NewowTrendChartMarker): number {
  return marker.family === 'cup'
    ? CUP_MARKER_PRIORITY[marker.markerType] ?? Number.MAX_SAFE_INTEGER
    : 0
}

function genericTradingDay(bar: BarData): string | null {
  if (typeof bar.trading_day === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(bar.trading_day)) {
    return bar.trading_day
  }
  const day = bar.time.slice(0, 10)
  return /^\d{4}-\d{2}-\d{2}$/.test(day) ? day : null
}

function validOhlcv(bar: BarData): boolean {
  return [bar.open, bar.high, bar.low, bar.close, bar.volume].every(Number.isFinite)
    && bar.low <= bar.open && bar.open <= bar.high
    && bar.low <= bar.close && bar.close <= bar.high
    && bar.volume >= 0
}

function finiteOrNull(value: number | undefined): number | null {
  return value !== undefined && Number.isFinite(value) ? value : null
}

function instantDay(value: string): string | null {
  const timestamp = Date.parse(value)
  return Number.isFinite(timestamp) ? value.slice(0, 10) : null
}

export function resolveNewowTrendCrosshairFacts(
  projection: NewowTrendChartProjection,
  time: Time,
): NewowTrendHoverFacts | null {
  const day = chartDay(time)
  return day === null
    ? null
    : projection.hoverFacts.find((facts) => facts.tradingDay === day) ?? null
}

function chartDay(time: Time): string | null {
  if (typeof time === 'string') return time.slice(0, 10)
  if (typeof time === 'number') return null
  return `${time.year}-${String(time.month).padStart(2, '0')}-${String(time.day).padStart(2, '0')}`
}

export interface NewowTrendPrimitiveStyle {
  readonly yellowFill: string
  readonly blueFill: string
  readonly bullishCup: string
  readonly bearishCup: string
  readonly pivot: string
  readonly rollover: string
  readonly rolloverText: string
}

export const NEWOW_TREND_PRIMITIVE_STYLE: NewowTrendPrimitiveStyle = {
  yellowFill: 'rgba(245, 158, 11, 0.16)',
  blueFill: 'rgba(37, 99, 235, 0.14)',
  bullishCup: '#D97706',
  bearishCup: '#2563EB',
  pivot: '#7C3AED',
  rollover: 'rgba(91, 113, 143, 0.72)',
  rolloverText: '#5B718F',
}

export type NewowTrendPrimitiveDrawCommand =
  | {
    readonly kind: 'band'
    readonly points: readonly [number, number][]
    readonly color: string
  }
  | {
    readonly kind: 'cup-segment' | 'cup-pivot'
    readonly fromX: number
    readonly toX: number
    readonly fromY: number
    readonly toY: number
    readonly color: string
    readonly dashed: boolean
  }
  | {
    readonly kind: 'rollover'
    readonly fromX: number
    readonly label: string
    readonly color: string
    readonly textColor: string
  }

export function newowTrendPrimitiveDrawCommands(
  projection: Pick<NewowTrendChartProjection, 'band' | 'cups' | 'rolloverSeams'>,
  xOf: (tradingDay: string) => number | null,
  yOf: (price: number) => number | null,
  style: NewowTrendPrimitiveStyle = NEWOW_TREND_PRIMITIVE_STYLE,
): NewowTrendPrimitiveDrawCommand[] {
  const commands: NewowTrendPrimitiveDrawCommand[] = []
  for (const area of projection.band.areas) {
    const fromX = xOf(area.fromTradingDay)
    const throughX = xOf(area.throughTradingDay)
    const fromB = yOf(area.fromB)
    const fromC = yOf(area.fromC)
    const throughB = yOf(area.throughB)
    const throughC = yOf(area.throughC)
    if (![fromX, throughX, fromB, fromC, throughB, throughC].every(isCoordinate)) continue
    commands.push({
      kind: 'band',
      points: [[fromX!, fromB!], [throughX!, throughB!], [throughX!, throughC!], [fromX!, fromC!]],
      color: area.state === 'YELLOW' ? style.yellowFill : style.blueFill,
    })
  }
  for (const cup of projection.cups) {
    const color = cup.direction === 'BULLISH' ? style.bullishCup : style.bearishCup
    for (let index = 1; index < cup.points.length; index += 1) {
      const previous = cup.points[index - 1]!
      const current = cup.points[index]!
      appendLine(commands, 'cup-segment', previous.tradingDay, current.tradingDay, previous.price, current.price, color, false, xOf, yOf)
    }
    if (cup.pivotLine !== null) {
      appendLine(
        commands,
        'cup-pivot',
        cup.pivotLine.fromTradingDay,
        cup.pivotLine.throughTradingDay,
        cup.pivotLine.price,
        cup.pivotLine.price,
        style.pivot,
        true,
        xOf,
        yOf,
      )
    }
  }
  for (const seam of projection.rolloverSeams) {
    const x = xOf(seam.tradingDay)
    if (!isCoordinate(x)) continue
    commands.push({
      kind: 'rollover', fromX: x, label: seam.label,
      color: style.rollover, textColor: style.rolloverText,
    })
  }
  return commands
}

function appendLine(
  commands: NewowTrendPrimitiveDrawCommand[],
  kind: 'cup-segment' | 'cup-pivot',
  fromDay: string,
  throughDay: string,
  fromPrice: number,
  throughPrice: number,
  color: string,
  dashed: boolean,
  xOf: (tradingDay: string) => number | null,
  yOf: (price: number) => number | null,
): void {
  const fromX = xOf(fromDay)
  const toX = xOf(throughDay)
  const fromY = yOf(fromPrice)
  const toY = yOf(throughPrice)
  if (![fromX, toX, fromY, toY].every(isCoordinate)) return
  commands.push({ kind, fromX: fromX!, toX: toX!, fromY: fromY!, toY: toY!, color, dashed })
}

function isCoordinate(value: number | null): value is number {
  return value !== null && Number.isFinite(value)
}

interface MediaTarget {
  useMediaCoordinateSpace(fn: (scope: {
    context: CanvasRenderingContext2D
    mediaSize: { width: number; height: number }
  }) => void): void
}

export class NewowTrendChartPrimitive implements ISeriesPrimitive<Time> {
  private chart: IChartApi | null = null
  private series: ISeriesApi<SeriesType, Time> | null = null
  private requestUpdate: (() => void) | null = null
  private projection: Pick<NewowTrendChartProjection, 'band' | 'cups' | 'rolloverSeams'> = {
    band: { b: [], c: [], areas: [] }, cups: [], rolloverSeams: [],
  }
  private timeOf: ((tradingDay: string) => Time | null) | null = null
  private style: NewowTrendPrimitiveStyle = NEWOW_TREND_PRIMITIVE_STYLE
  private readonly paneView = new NewowTrendPaneView()
  private readonly paneViewList: IPrimitivePaneView[] = [this.paneView]

  setData(
    projection: Pick<NewowTrendChartProjection, 'band' | 'cups' | 'rolloverSeams'>,
    timeOf: (tradingDay: string) => Time | null,
  ): void {
    this.projection = projection
    this.timeOf = timeOf
    this.requestUpdate?.()
  }

  setStyle(style: NewowTrendPrimitiveStyle): void {
    this.style = style
    this.requestUpdate?.()
  }

  attached(param: SeriesAttachedParameter<Time>): void {
    this.chart = param.chart as IChartApi
    this.series = param.series
    this.requestUpdate = param.requestUpdate
  }

  detached(): void {
    this.chart = null
    this.series = null
    this.requestUpdate = null
  }

  updateAllViews(): void {
    this.paneView.update(this.projectCommands())
  }

  paneViews(): readonly IPrimitivePaneView[] {
    return this.paneViewList
  }

  private projectCommands(): NewowTrendPrimitiveDrawCommand[] {
    if (this.chart === null || this.series === null || this.timeOf === null) return []
    return newowTrendPrimitiveDrawCommands(
      this.projection,
      (day) => {
        const time = this.timeOf!(day)
        return time === null ? null : this.chart!.timeScale().timeToCoordinate(time)
      },
      (price) => this.series!.priceToCoordinate(price),
      this.style,
    )
  }
}

class NewowTrendPaneView implements IPrimitivePaneView {
  private paneRenderer = new NewowTrendRenderer([])

  zOrder() {
    return 'normal' as const
  }

  update(commands: readonly NewowTrendPrimitiveDrawCommand[]): void {
    this.paneRenderer = new NewowTrendRenderer(commands)
  }

  renderer(): IPrimitivePaneRenderer {
    return this.paneRenderer as IPrimitivePaneRenderer
  }
}

class NewowTrendRenderer {
  private readonly commands: readonly NewowTrendPrimitiveDrawCommand[]

  constructor(commands: readonly NewowTrendPrimitiveDrawCommand[]) {
    this.commands = commands
  }

  draw(target: MediaTarget): void {
    target.useMediaCoordinateSpace(({ context, mediaSize }) => {
      context.save()
      for (const command of this.commands) drawCommand(context, mediaSize.height, command)
      context.restore()
    })
  }
}

function drawCommand(
  context: CanvasRenderingContext2D,
  height: number,
  command: NewowTrendPrimitiveDrawCommand,
): void {
  if (command.kind === 'band') {
    context.beginPath()
    context.moveTo(command.points[0]![0], command.points[0]![1])
    for (const [x, y] of command.points.slice(1)) context.lineTo(x, y)
    context.closePath()
    context.fillStyle = command.color
    context.fill()
    return
  }
  if (command.kind === 'rollover') {
    context.beginPath()
    context.setLineDash([3, 4])
    context.moveTo(command.fromX, 0)
    context.lineTo(command.fromX, height)
    context.strokeStyle = command.color
    context.lineWidth = 1
    context.stroke()
    context.setLineDash([])
    context.fillStyle = command.textColor
    context.font = '11px sans-serif'
    context.fillText(command.label, command.fromX + 5, 18)
    return
  }
  context.beginPath()
  context.setLineDash(command.dashed ? [5, 4] : [])
  context.moveTo(command.fromX, command.fromY)
  context.lineTo(command.toX, command.toY)
  context.strokeStyle = command.color
  context.lineWidth = command.kind === 'cup-segment' ? 1.5 : 1
  context.stroke()
  context.setLineDash([])
}

export interface NewowTrendChartDisposerResources {
  readonly unsubscribeCrosshair: () => void
  readonly disconnectResizeObserver: () => void
  readonly removeChart: () => void
}

export interface NewowTrendResizeObserver {
  observe(target: Element): void
  disconnect(): void
}

export interface NewowTrendChartAdapter {
  readonly createChart: typeof import('lightweight-charts').createChart
  readonly createSeriesMarkers: typeof import('lightweight-charts').createSeriesMarkers
  readonly createResizeObserver: (callback: ResizeObserverCallback) => NewowTrendResizeObserver
}

export const NEWOW_TREND_CHART_ADAPTER_KEY: InjectionKey<NewowTrendChartAdapter> = Symbol(
  'newow-trend-chart-adapter',
)

/** Owns the stage's external resources and makes teardown idempotent. */
export function createNewowTrendChartDisposer(
  resources: NewowTrendChartDisposerResources,
): () => void {
  let disposed = false
  return () => {
    if (disposed) return
    disposed = true
    resources.unsubscribeCrosshair()
    resources.disconnectResizeObserver()
    resources.removeChart()
  }
}
