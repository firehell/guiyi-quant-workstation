import type { IPrimitivePaneRenderer, IPrimitivePaneView, ISeriesPrimitive, SeriesAttachedParameter, Time } from 'lightweight-charts'
import type { NewowProductBandArea } from './newowProductChartPrimitives.ts'

/** Paints only adjacent, validated same-owner A/B polygons projected by the chart model. */
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
      for (const area of this.areas) {
        const x1 = attachment.chart.timeScale().timeToCoordinate(area.from.time)
        const x2 = attachment.chart.timeScale().timeToCoordinate(area.through.time)
        const a1 = attachment.series.priceToCoordinate(area.from.a)
        const b1 = attachment.series.priceToCoordinate(area.from.b)
        const a2 = attachment.series.priceToCoordinate(area.through.a)
        const b2 = attachment.series.priceToCoordinate(area.through.b)
        if (x1 === null || x2 === null || a1 === null || b1 === null || a2 === null || b2 === null) continue
        context.beginPath()
        context.moveTo(x1, a1); context.lineTo(x2, a2); context.lineTo(x2, b2); context.lineTo(x1, b1)
        context.closePath(); context.fillStyle = area.color; context.fill()
      }
      context.restore()
    })
  }
}
