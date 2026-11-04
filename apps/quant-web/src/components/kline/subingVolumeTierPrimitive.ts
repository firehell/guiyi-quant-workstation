import type { IChartApi, IPrimitivePaneRenderer, IPrimitivePaneView, ISeriesApi, ISeriesPrimitive, SeriesAttachedParameter, SeriesType, Time } from 'lightweight-charts'

export interface SubingVolumeTierMark { time: Time; volume: number; tier: 2 | 3 }
export const SUBING_VOLUME_TIER_COLORS = { light: { 2: '#3185EE', 3: '#9B59E5' }, dark: { 2: '#65A9FF', 3: '#C38BFF' } } as const

/** Volume-axis anchored marks automatically follow native pan, zoom, scale and resize. */
export class SubingVolumeTierPrimitive implements ISeriesPrimitive<Time> {
  private chart: IChartApi | null = null
  private series: ISeriesApi<SeriesType, Time> | null = null
  private requestUpdate: (() => void) | null = null
  private points: readonly SubingVolumeTierMark[] = []
  private theme: 'light' | 'dark' = 'light'
  private renderer: IPrimitivePaneRenderer = { draw: target => target.useMediaCoordinateSpace(({ context, mediaSize }) => {
    if (!this.chart || !this.series) return
    const scale = this.chart.timeScale()
    const compact = scale.options().barSpacing < 5
    context.save()
    context.beginPath(); context.rect(0, 0, mediaSize.width, mediaSize.height); context.clip()
    for (const point of this.points) {
      const x = scale.timeToCoordinate(point.time), top = this.series.priceToCoordinate(point.volume)
      const radius = point.tier === 3 ? compact ? 3 : 4 : compact ? 1.75 : 2.5
      if (x === null || top === null || !Number.isFinite(x) || !Number.isFinite(top)
        || x < radius || x > mediaSize.width - radius) continue
      const y = top - radius - 3
      if (y - radius < 0 || y + radius > mediaSize.height) continue
      context.fillStyle = SUBING_VOLUME_TIER_COLORS[this.theme][point.tier]
      context.beginPath()
      if (point.tier === 2) context.arc(x, y, radius, 0, Math.PI * 2)
      else {
        context.moveTo(x, y - radius); context.lineTo(x + radius, y)
        context.lineTo(x, y + radius); context.lineTo(x - radius, y); context.closePath()
      }
      context.fill()
    }
    context.restore()
  }) }
  private view: IPrimitivePaneView = { zOrder: () => 'top', renderer: () => this.renderer }
  attached(value: SeriesAttachedParameter<Time>) { this.chart = value.chart as IChartApi; this.series = value.series; this.requestUpdate = value.requestUpdate }
  detached() { this.chart = null; this.series = null; this.requestUpdate = null }
  paneViews() { return [this.view] }
  setData(points: readonly SubingVolumeTierMark[], theme: 'light' | 'dark' = 'light') { this.points = points; this.theme = theme; this.requestUpdate?.() }
}
