import type { IPrimitivePaneRenderer, IPrimitivePaneView, ISeriesPrimitive, SeriesAttachedParameter, Time } from 'lightweight-charts'
import type { NewowProductBandArea } from './newowProductChartPrimitives.ts'

/** Paints one centered A/B column per validated Bar projected by the chart model. */
export class NewowProductBandPrimitive implements ISeriesPrimitive<Time> {
  private attachment: SeriesAttachedParameter<Time> | null = null
  private areas: readonly NewowProductBandArea[] = []
  private readonly view: IPrimitivePaneView = {
    zOrder: () => 'bottom',
    renderer: () => ({ draw: target => this.draw(target) }),
  }

  attached(attachment: SeriesAttachedParameter<Time>): void { this.attachment = attachment }
  detached(): void { this.attachment = null; this.areas = [] }
  paneViews(): readonly IPrimitivePaneView[] { return [this.view] }
  setData(areas: readonly NewowProductBandArea[]): void {
    this.areas = areas
    this.attachment?.requestUpdate()
  }

  private draw(target: Parameters<IPrimitivePaneRenderer['draw']>[0]): void {
    const attachment = this.attachment
    if (!attachment) return
    target.useMediaCoordinateSpace(({ context }) => {
      context.save()
      const timeScale = attachment.chart.timeScale()
      const width = timeScale.options().barSpacing * 0.8
      for (const area of this.areas) {
        const x = timeScale.timeToCoordinate(area.time)
        const a = attachment.series.priceToCoordinate(area.a)
        const b = attachment.series.priceToCoordinate(area.b)
        if (x === null || a === null || b === null) continue
        context.fillStyle = area.color
        context.fillRect(x - width / 2, Math.min(a, b), width, Math.abs(a - b))
      }
      context.restore()
    })
  }
}
