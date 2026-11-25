import type {
  IPrimitivePaneRenderer, IPrimitivePaneView, ISeriesPrimitive, SeriesAttachedParameter, Time,
} from 'lightweight-charts'

export interface ExecutionOverlayPoint {
  from: Time
  to: Time
  ratio: number
  price: number
  source: '快期原生委托' | '快期原生成交' | '苏冰模型成交'
}

export class ExecutionOverlayPrimitive implements ISeriesPrimitive<Time> {
  private chartContext: SeriesAttachedParameter<Time> | null = null
  private points: readonly ExecutionOverlayPoint[] = []
  private renderer: IPrimitivePaneRenderer = {
    draw: target => target.useMediaCoordinateSpace(({ context, mediaSize }) => {
      if (!this.chartContext) return
      const { chart, series } = this.chartContext
      const scale = chart.timeScale()
      context.save()
      context.beginPath()
      context.rect(0, 0, mediaSize.width, mediaSize.height)
      context.clip()
      for (const point of this.points) {
        const from = scale.timeToCoordinate(point.from)
        const to = scale.timeToCoordinate(point.to)
        const y = series.priceToCoordinate(point.price)
        if (from === null || to === null || y === null) continue
        const x = from + (to - from) * point.ratio
        if (x < 0 || x > mediaSize.width || y < 0 || y > mediaSize.height) continue
        const native = point.source !== '苏冰模型成交'
        const order = point.source === '快期原生委托'
        context.fillStyle = native ? '#235bc5' : '#782eb5'
        context.strokeStyle = order ? '#235bc5' : '#fff'
        context.lineWidth = order ? 2 : 1
        context.beginPath()
        if (native) context.rect(x - 4, y - 4, 8, 8)
        else context.arc(x, y, 4.5, 0, Math.PI * 2)
        if (!order) context.fill()
        context.stroke()
      }
      context.restore()
    }),
  }
  private view: IPrimitivePaneView = { zOrder: () => 'top', renderer: () => this.renderer }
  attached(context: SeriesAttachedParameter<Time>) { this.chartContext = context }
  detached() { this.chartContext = null }
  paneViews() { return [this.view] }
  setData(points: readonly ExecutionOverlayPoint[]) {
    this.points = points
    this.chartContext?.requestUpdate()
  }
}
