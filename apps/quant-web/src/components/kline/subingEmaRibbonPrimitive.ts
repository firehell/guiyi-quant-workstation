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
import {
  SUBING_EMA_RIBBON_STYLE,
  type SubingEmaRibbonPoint,
  type SubingEmaRibbonTone,
} from '@/utils/subingEmaRibbon'

interface RibbonCoordinate {
  x: number
  y10: number
  y21: number
  tone: SubingEmaRibbonTone
}

interface MediaTarget {
  useMediaCoordinateSpace(fn: (scope: { context: CanvasRenderingContext2D }) => void): void
}

export class SubingEmaRibbonPrimitive implements ISeriesPrimitive<Time> {
  private chart: IChartApi | null = null
  private series: ISeriesApi<SeriesType, Time> | null = null
  private requestUpdate: (() => void) | null = null
  private points: readonly SubingEmaRibbonPoint[] = []
  private timeOf: ((iso: string) => Time | null) | null = null
  private readonly paneView = new SubingEmaRibbonPaneView()
  private readonly paneViewList: IPrimitivePaneView[] = [this.paneView]

  setData(
    points: readonly SubingEmaRibbonPoint[],
    timeOf: (iso: string) => Time | null,
  ): void {
    this.points = points
    this.timeOf = timeOf
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
    this.paneView.update(this.projectPoints())
  }

  paneViews(): readonly IPrimitivePaneView[] {
    return this.paneViewList
  }

  private projectPoints(): RibbonCoordinate[] {
    if (!this.chart || !this.series || !this.timeOf) return []
    return this.points.flatMap((point) => {
      const time = this.timeOf!(point.time)
      if (time === null) return []
      const x = this.chart!.timeScale().timeToCoordinate(time)
      const y10 = this.series!.priceToCoordinate(point.ema10)
      const y21 = this.series!.priceToCoordinate(point.ema21)
      if (x === null || y10 === null || y21 === null) return []
      return [{ x, y10, y21, tone: point.tone }]
    })
  }
}

class SubingEmaRibbonPaneView implements IPrimitivePaneView {
  private paneRenderer = new SubingEmaRibbonRenderer([])

  zOrder() {
    return 'bottom' as const
  }

  update(points: readonly RibbonCoordinate[]): void {
    this.paneRenderer = new SubingEmaRibbonRenderer(points)
  }

  renderer(): IPrimitivePaneRenderer {
    return this.paneRenderer as IPrimitivePaneRenderer
  }
}

class SubingEmaRibbonRenderer {
  private readonly points: readonly RibbonCoordinate[]

  constructor(points: readonly RibbonCoordinate[]) {
    this.points = points
  }

  draw(target: MediaTarget): void {
    target.useMediaCoordinateSpace(({ context }) => {
      this.points.forEach((point, index) => {
        drawRibbonColumn(context, point, deriveColumnWidth(this.points, index))
      })
      drawEmaLine(context, this.points, 'y10', SUBING_EMA_RIBBON_STYLE.ema10Line)
      drawEmaLine(context, this.points, 'y21', SUBING_EMA_RIBBON_STYLE.ema21Line)
    })
  }
}

function deriveColumnWidth(
  points: readonly Pick<RibbonCoordinate, 'x'>[],
  index: number,
): number {
  const current = points[index]
  if (!current) return 1

  const previousGap = index > 0 ? current.x - points[index - 1]!.x : null
  const nextGap = index + 1 < points.length ? points[index + 1]!.x - current.x : null
  const gaps = [previousGap, nextGap].filter(
    (gap): gap is number => gap !== null && Number.isFinite(gap) && gap > 0,
  )

  if (gaps.length === 0) return 1
  const spacing = Math.min(...gaps)
  return Math.max(1, Math.min(spacing - 1, Math.floor(spacing * 0.8)))
}

function drawRibbonColumn(
  context: CanvasRenderingContext2D,
  point: RibbonCoordinate,
  width: number,
): void {
  const top = Math.min(point.y10, point.y21)
  const bottom = Math.max(point.y10, point.y21)
  const left = Math.round(point.x - width / 2)
  const drawWidth = Math.max(1, Math.round(width))
  const height = Math.max(1, Math.round(bottom - top))

  context.fillStyle = point.tone === 'bull'
    ? SUBING_EMA_RIBBON_STYLE.bullFill
    : SUBING_EMA_RIBBON_STYLE.bearFill
  context.fillRect(left, Math.round(top), drawWidth, height)
}

function drawEmaLine(
  context: CanvasRenderingContext2D,
  points: readonly RibbonCoordinate[],
  key: 'y10' | 'y21',
  color: string,
): void {
  if (points.length < 2) return
  context.beginPath()
  context.moveTo(points[0]!.x, points[0]![key])
  for (let index = 1; index < points.length; index += 1) {
    context.lineTo(points[index]!.x, points[index]![key])
  }
  context.strokeStyle = color
  context.lineWidth = 1
  context.stroke()
}
