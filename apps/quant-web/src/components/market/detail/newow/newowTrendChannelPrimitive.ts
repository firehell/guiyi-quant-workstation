import type { IPrimitivePaneRenderer, IPrimitivePaneView, ISeriesPrimitive, SeriesAttachedParameter, Time } from 'lightweight-charts'

export interface NewowTrendChannelPrimitivePoint {
  readonly time: Time
  readonly upper: number
  readonly lower: number
}

const UPPER_COLOR = 'rgba(52, 199, 89, 0.9)'
const LOWER_COLOR = 'rgba(255, 59, 48, 0.9)'
const RADIUS = 2.5

/** Paints independent server-owned channel dots in true time/price coordinates. */
export class NewowTrendChannelPrimitive implements ISeriesPrimitive<Time> {
  private attachment: SeriesAttachedParameter<Time> | null = null
  private points: readonly NewowTrendChannelPrimitivePoint[] = []
  private readonly view: IPrimitivePaneView = {
    zOrder: () => 'normal',
    renderer: () => ({ draw: target => this.draw(target) }),
  }

  attached(attachment: SeriesAttachedParameter<Time>): void { this.attachment = attachment }
  detached(): void { this.attachment = null; this.points = [] }
  paneViews(): readonly IPrimitivePaneView[] { return [this.view] }
  setData(points: readonly NewowTrendChannelPrimitivePoint[]): void {
    this.points = points
    this.attachment?.requestUpdate()
  }

  private draw(target: Parameters<IPrimitivePaneRenderer['draw']>[0]): void {
    const attachment = this.attachment
    if (attachment === null) return
    target.useMediaCoordinateSpace(({ context }) => {
      context.save()
      const timeScale = attachment.chart.timeScale()
      for (const point of this.points) {
        const x = timeScale.timeToCoordinate(point.time)
        const upper = attachment.series.priceToCoordinate(point.upper)
        const lower = attachment.series.priceToCoordinate(point.lower)
        if (x === null || upper === null || lower === null) continue
        context.fillStyle = UPPER_COLOR
        context.beginPath()
        context.arc(x, upper, RADIUS, 0, Math.PI * 2)
        context.fill()
        context.fillStyle = LOWER_COLOR
        context.beginPath()
        context.arc(x, lower, RADIUS, 0, Math.PI * 2)
        context.fill()
      }
      context.restore()
    })
  }
}
