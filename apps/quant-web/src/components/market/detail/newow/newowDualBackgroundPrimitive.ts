import type { IPrimitivePaneRenderer, IPrimitivePaneView, ISeriesPrimitive, SeriesAttachedParameter, Time } from 'lightweight-charts'

/** Full price-pane shading for ready trend blue-band Bars, behind candles. */
export class NewowDualBackgroundPrimitive implements ISeriesPrimitive<Time> {
  private attachment: SeriesAttachedParameter<Time> | null = null
  private times: readonly Time[] = []
  private readonly view: IPrimitivePaneView = { zOrder: () => 'bottom', renderer: () => ({ draw: target => this.draw(target) }) }
  attached(value: SeriesAttachedParameter<Time>): void { this.attachment = value }
  detached(): void { this.attachment = null; this.times = [] }
  paneViews(): readonly IPrimitivePaneView[] { return [this.view] }
  setData(times: readonly Time[]): void { this.times = times; this.attachment?.requestUpdate() }
  private draw(target: Parameters<IPrimitivePaneRenderer['draw']>[0]): void {
    const attachment = this.attachment
    if (!attachment) return
    target.useMediaCoordinateSpace(({ context, mediaSize }) => {
      const scale = attachment.chart.timeScale()
      const spacing = scale.options().barSpacing
      context.save(); context.fillStyle = 'rgba(0,0,0,0.055)'
      for (const time of this.times) {
        const x = scale.timeToCoordinate(time)
        if (x !== null) context.fillRect(x - spacing / 2, 0, spacing, mediaSize.height)
      }
      context.restore()
    })
  }
}
