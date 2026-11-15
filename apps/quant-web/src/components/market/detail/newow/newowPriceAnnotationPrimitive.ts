import type { IPrimitivePaneRenderer, IPrimitivePaneView, ISeriesPrimitive, SeriesAttachedParameter, Time } from 'lightweight-charts'

export interface NewowPriceAnnotation {
  time: Time
  index: number
  price: number
  side: 'high' | 'low'
  text: string
  kind: 'extremum' | 'nine'
  count?: number
}

export class NewowPriceAnnotationPrimitive implements ISeriesPrimitive<Time> {
  private attachment: SeriesAttachedParameter<Time> | null = null
  private marks: readonly NewowPriceAnnotation[] = []
  private dark = false
  private readonly view: IPrimitivePaneView = {
    zOrder: () => 'normal',
    renderer: () => ({ draw: target => this.draw(target) }),
  }

  attached(value: SeriesAttachedParameter<Time>): void { this.attachment = value }
  detached(): void { this.attachment = null; this.marks = [] }
  paneViews(): readonly IPrimitivePaneView[] { return [this.view] }

  setData(marks: readonly NewowPriceAnnotation[], dark: boolean): void {
    this.marks = marks
    this.dark = dark
    this.attachment?.requestUpdate()
  }

  private draw(target: Parameters<IPrimitivePaneRenderer['draw']>[0]): void {
    const attachment = this.attachment
    const scale = attachment?.chart.timeScale()
    const range = scale?.getVisibleLogicalRange()
    if (!attachment || !scale || !range || !this.marks.length) return
    // Companion layers can insert times between primary bars.
    let lo = 0, hi = this.marks.length
    while (lo < hi) {
      const mid = (lo + hi) >>> 1
      const logicalIndex = scale.timeToIndex(this.marks[mid]!.time)
      if (logicalIndex === null) { lo = 0; break }
      if (logicalIndex < Math.floor(range.from)) lo = mid + 1
      else hi = mid
    }
    target.useMediaCoordinateSpace(({ context, mediaSize }) => {
      context.save()
      context.font = '600 10px system-ui, sans-serif'
      context.textAlign = 'center'
      for (let i = lo; i < this.marks.length; i++) {
        const mark = this.marks[i]!
        const x = scale.timeToCoordinate(mark.time)
        if (x === null || x < 0) continue
        if (x > mediaSize.width) break
        const y = attachment.series.priceToCoordinate(mark.price)
        if (y === null || y < 0 || y > mediaSize.height) continue
        const upper = mark.side === 'high'
        const distance = mark.kind === 'extremum' ? 2 : upper ? 18 : 24
        const green = upper ? mark.count === 9 : mark.count !== 9
        context.fillStyle = mark.kind === 'extremum'
          ? (this.dark ? '#d1d5db' : '#334155')
          : green ? (this.dark ? '#4ade80' : '#067647') : (this.dark ? '#f472b6' : '#a31665')
        context.textBaseline = upper ? 'bottom' : 'top'
        const half = context.measureText(mark.text).width / 2
        context.fillText(mark.text, Math.max(half, Math.min(mediaSize.width - half, x)),
          upper ? Math.max(10, y - distance) : Math.min(mediaSize.height - 10, y + distance))
      }
      context.restore()
    })
  }
}
