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
  splitRibbonCoordinates,
  type SubingEmaRibbonBand,
  type SubingEmaRibbonTone,
} from '@/utils/subingEmaRibbon'

interface RibbonCoordinate {
  x: number
  y10: number
  y21: number
}

interface RibbonViewBand {
  left: RibbonCoordinate
  right: RibbonCoordinate
  leftTone: SubingEmaRibbonTone
  rightTone: SubingEmaRibbonTone
  splitT: number | null
}

interface MediaTarget {
  useMediaCoordinateSpace(fn: (scope: { context: CanvasRenderingContext2D }) => void): void
}

export class SubingEmaRibbonPrimitive implements ISeriesPrimitive<Time> {
  private chart: IChartApi | null = null
  private series: ISeriesApi<SeriesType, Time> | null = null
  private requestUpdate: (() => void) | null = null
  private bands: readonly SubingEmaRibbonBand[] = []
  private timeOf: ((iso: string) => Time | null) | null = null
  private readonly paneView = new SubingEmaRibbonPaneView()
  private readonly paneViewList: IPrimitivePaneView[] = [this.paneView]

  setData(
    bands: readonly SubingEmaRibbonBand[],
    timeOf: (iso: string) => Time | null,
  ): void {
    this.bands = bands
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
    this.paneView.update(this.projectBands())
  }

  paneViews(): readonly IPrimitivePaneView[] {
    return this.paneViewList
  }

  private projectBands(): RibbonViewBand[] {
    if (!this.chart || !this.series || !this.timeOf) return []
    return this.bands.flatMap((band) => {
      const left = this.projectPoint(band.left)
      const right = this.projectPoint(band.right)
      if (!left || !right) return []
      return [{
        left,
        right,
        leftTone: band.leftTone,
        rightTone: band.rightTone,
        splitT: band.splitT,
      }]
    })
  }

  private projectPoint(point: SubingEmaRibbonBand['left']): RibbonCoordinate | null {
    const time = this.timeOf!(point.time)
    if (time === null) return null
    const x = this.chart!.timeScale().timeToCoordinate(time)
    const y10 = this.series!.priceToCoordinate(point.ema10)
    const y21 = this.series!.priceToCoordinate(point.ema21)
    if (x === null || y10 === null || y21 === null) return null
    return { x, y10, y21 }
  }
}

class SubingEmaRibbonPaneView implements IPrimitivePaneView {
  private paneRenderer = new SubingEmaRibbonRenderer([])

  zOrder() {
    return 'bottom' as const
  }

  update(bands: RibbonViewBand[]): void {
    this.paneRenderer = new SubingEmaRibbonRenderer(bands)
  }

  renderer(): IPrimitivePaneRenderer {
    return this.paneRenderer as IPrimitivePaneRenderer
  }
}

class SubingEmaRibbonRenderer {
  private readonly bands: readonly RibbonViewBand[]

  constructor(bands: readonly RibbonViewBand[]) {
    this.bands = bands
  }

  draw(target: MediaTarget): void {
    target.useMediaCoordinateSpace(({ context }) => {
      for (const band of this.bands) {
        const mid = band.splitT === null || band.leftTone === band.rightTone
          ? null
          : splitRibbonCoordinates(band.left, band.right, band.splitT)
        if (mid === null) {
          fillRibbonQuad(context, band.left, band.right, band.leftTone)
          strokeRibbonEdges(context, band.left, band.right, band.leftTone)
          continue
        }
        if (band.splitT! > 0) {
          fillRibbonQuad(context, band.left, mid, band.leftTone)
          strokeRibbonEdges(context, band.left, mid, band.leftTone)
        }
        if (band.splitT! < 1) {
          fillRibbonQuad(context, mid, band.right, band.rightTone)
          strokeRibbonEdges(context, mid, band.right, band.rightTone)
        }
      }
    })
  }
}

function fillRibbonQuad(
  context: CanvasRenderingContext2D,
  left: RibbonCoordinate,
  right: RibbonCoordinate,
  tone: SubingEmaRibbonTone,
): void {
  context.beginPath()
  context.moveTo(left.x, left.y10)
  context.lineTo(right.x, right.y10)
  context.lineTo(right.x, right.y21)
  context.lineTo(left.x, left.y21)
  context.closePath()
  context.fillStyle = SUBING_EMA_RIBBON_STYLE[tone].fill
  context.fill()
}

function strokeRibbonEdges(
  context: CanvasRenderingContext2D,
  left: RibbonCoordinate,
  right: RibbonCoordinate,
  tone: SubingEmaRibbonTone,
): void {
  context.beginPath()
  context.moveTo(left.x, left.y10)
  context.lineTo(right.x, right.y10)
  context.moveTo(left.x, left.y21)
  context.lineTo(right.x, right.y21)
  context.strokeStyle = SUBING_EMA_RIBBON_STYLE[tone].stroke
  context.lineWidth = 1
  context.stroke()
}
