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

import type { RangeDetectorVisualRange } from '@/utils/rangeDetectorLux'

export interface RangeDetectorPrimitiveStyle {
  rangeIntact: string
  rangeBrokenUp: string
  rangeBrokenDown: string
  rangeFill: string
  rangeMid: string
}

export const RANGE_DETECTOR_PRIMITIVE_STYLE: RangeDetectorPrimitiveStyle = {
  rangeIntact: '#2563EB',
  rangeBrokenUp: '#16A34A',
  rangeBrokenDown: '#DC2626',
  rangeFill: 'rgba(37, 99, 235, 0.10)',
  rangeMid: 'rgba(37, 99, 235, 0.65)',
}

export interface RangeDetectorDrawCommand {
  kind: 'box' | 'upper' | 'lower' | 'mid' | 'confirmation'
  fromX: number
  toX: number
  topY?: number
  bottomY?: number
  y?: number
  color: string
  dashed: boolean
}

export function rangeDetectorDrawCommands(
  ranges: readonly RangeDetectorVisualRange[],
  lastBarTime: string | null,
  xOf: (iso: string) => number | null,
  yOf: (price: number) => number | null,
  style: RangeDetectorPrimitiveStyle = RANGE_DETECTOR_PRIMITIVE_STYLE,
): RangeDetectorDrawCommand[] {
  if (!lastBarTime) return []
  const commands: RangeDetectorDrawCommand[] = []
  for (const range of ranges) {
    appendBox(commands, range, xOf, yOf, style)
    appendLevels(commands, range, lastBarTime, xOf, yOf, style)
    appendConfirmation(commands, range, xOf, yOf, style)
  }
  return commands
}

function appendBox(
  commands: RangeDetectorDrawCommand[],
  range: RangeDetectorVisualRange,
  xOf: (iso: string) => number | null,
  yOf: (price: number) => number | null,
  style: RangeDetectorPrimitiveStyle,
): void {
  const fromX = xOf(range.visualStartAt)
  const toX = xOf(range.detectionRightAt)
  const topY = yOf(range.upper)
  const bottomY = yOf(range.lower)
  if (!isCoordinate(fromX) || !isCoordinate(toX) || !isCoordinate(topY) || !isCoordinate(bottomY)) return
  commands.push({ kind: 'box', fromX, toX, topY, bottomY, color: style.rangeFill, dashed: false })
}

function appendLevels(
  commands: RangeDetectorDrawCommand[],
  range: RangeDetectorVisualRange,
  lastBarTime: string,
  xOf: (iso: string) => number | null,
  yOf: (price: number) => number | null,
  style: RangeDetectorPrimitiveStyle,
): void {
  const fromX = xOf(range.levelsActiveFrom)
  const toX = xOf(range.levelsActiveUntil ?? lastBarTime)
  const upperY = yOf(range.upper)
  const lowerY = yOf(range.lower)
  const midY = yOf(range.mid)
  if (!isCoordinate(fromX) || !isCoordinate(toX) || !isCoordinate(upperY) || !isCoordinate(lowerY) || !isCoordinate(midY)) return
  const brokenTone = range.state === 'broken_up' ? style.rangeBrokenUp
    : range.state === 'broken_down' ? style.rangeBrokenDown
      : null
  const brokenX = brokenTone && range.brokenAt ? xOf(range.brokenAt) : null
  if (brokenTone && isCoordinate(brokenX) && brokenX >= fromX && brokenX <= toX) {
    appendLevelTriplet(commands, fromX, brokenX, upperY, lowerY, midY, style.rangeIntact, style.rangeMid)
    appendLevelTriplet(commands, brokenX, toX, upperY, lowerY, midY, brokenTone, brokenTone)
    return
  }
  const color = brokenTone ?? style.rangeIntact
  appendLevelTriplet(commands, fromX, toX, upperY, lowerY, midY, color, brokenTone ?? style.rangeMid)
}

function appendLevelTriplet(
  commands: RangeDetectorDrawCommand[],
  fromX: number,
  toX: number,
  upperY: number,
  lowerY: number,
  midY: number,
  lineColor: string,
  midColor: string,
): void {
  commands.push({ kind: 'upper', fromX, toX, y: upperY, color: lineColor, dashed: false })
  commands.push({ kind: 'lower', fromX, toX, y: lowerY, color: lineColor, dashed: false })
  commands.push({ kind: 'mid', fromX, toX, y: midY, color: midColor, dashed: true })
}

function appendConfirmation(
  commands: RangeDetectorDrawCommand[],
  range: RangeDetectorVisualRange,
  xOf: (iso: string) => number | null,
  yOf: (price: number) => number | null,
  style: RangeDetectorPrimitiveStyle,
): void {
  const x = xOf(range.confirmedAt)
  const topY = yOf(range.upper)
  const bottomY = yOf(range.lower)
  if (!isCoordinate(x) || !isCoordinate(topY) || !isCoordinate(bottomY)) return
  commands.push({ kind: 'confirmation', fromX: x, toX: x, topY, bottomY, color: style.rangeMid, dashed: true })
}

function isCoordinate(value: number | null): value is number {
  return value !== null && Number.isFinite(value)
}

interface MediaTarget {
  useMediaCoordinateSpace(fn: (scope: { context: CanvasRenderingContext2D }) => void): void
}

export class RangeDetectorPrimitive implements ISeriesPrimitive<Time> {
  private chart: IChartApi | null = null
  private series: ISeriesApi<SeriesType, Time> | null = null
  private requestUpdate: (() => void) | null = null
  private ranges: readonly RangeDetectorVisualRange[] = []
  private lastBarTime: string | null = null
  private timeOf: ((iso: string) => Time | null) | null = null
  private style: RangeDetectorPrimitiveStyle = RANGE_DETECTOR_PRIMITIVE_STYLE
  private readonly paneView = new RangeDetectorPaneView()
  private readonly paneViewList: IPrimitivePaneView[] = [this.paneView]

  setData(ranges: readonly RangeDetectorVisualRange[], lastBarTime: string | null, timeOf: (iso: string) => Time | null): void {
    this.ranges = ranges
    this.lastBarTime = lastBarTime
    this.timeOf = timeOf
    this.requestUpdate?.()
  }

  setStyle(style: RangeDetectorPrimitiveStyle): void {
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

  private projectCommands(): RangeDetectorDrawCommand[] {
    if (!this.chart || !this.series || !this.timeOf) return []
    return rangeDetectorDrawCommands(
      this.ranges,
      this.lastBarTime,
      (iso) => {
        const time = this.timeOf!(iso)
        return time === null ? null : this.chart!.timeScale().timeToCoordinate(time)
      },
      (price) => this.series!.priceToCoordinate(price),
      this.style,
    )
  }
}

class RangeDetectorPaneView implements IPrimitivePaneView {
  private paneRenderer = new RangeDetectorRenderer([])

  zOrder() {
    return 'bottom' as const
  }

  update(commands: readonly RangeDetectorDrawCommand[]): void {
    this.paneRenderer = new RangeDetectorRenderer(commands)
  }

  renderer(): IPrimitivePaneRenderer {
    return this.paneRenderer as IPrimitivePaneRenderer
  }
}

class RangeDetectorRenderer {
  private readonly commands: readonly RangeDetectorDrawCommand[]

  constructor(commands: readonly RangeDetectorDrawCommand[]) {
    this.commands = commands
  }

  draw(target: MediaTarget): void {
    target.useMediaCoordinateSpace(({ context }) => {
      for (const command of this.commands) drawCommand(context, command)
    })
  }
}

function drawCommand(context: CanvasRenderingContext2D, command: RangeDetectorDrawCommand): void {
  if (command.kind === 'box') {
    context.fillStyle = command.color
    context.fillRect(command.fromX, Math.min(command.topY!, command.bottomY!), command.toX - command.fromX, Math.abs(command.bottomY! - command.topY!))
    return
  }
  context.beginPath()
  if (command.kind === 'confirmation') {
    context.moveTo(command.fromX, command.topY!)
    context.lineTo(command.toX, command.bottomY!)
  } else {
    context.moveTo(command.fromX, command.y!)
    context.lineTo(command.toX, command.y!)
  }
  context.setLineDash(command.dashed ? [3, 3] : [])
  context.strokeStyle = command.color
  context.lineWidth = command.kind === 'confirmation' ? 1 : 1.25
  context.stroke()
  context.setLineDash([])
}
