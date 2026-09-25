import type { IPrimitivePaneRenderer, IPrimitivePaneView, ISeriesPrimitive, SeriesAttachedParameter, Time } from 'lightweight-charts'
import type { NewowAlignedAuxiliaryChartModel } from './newowProductChartPrimitives'

export const NEWOW_TREND_REVERSAL_STYLE = {
  positive: '#ff403a', negative: '#30b458', rebound: '#ff9500', adjust: '#55bdee', axis: '#8b909a',
} as const

export interface TrendReversalDatum {
  readonly index: number
  readonly segmentId: string
  readonly time: Time
  readonly bias: number
  readonly rebound: number
  readonly adjust: number
}

export function buildNewowTrendReversalData(series: NewowAlignedAuxiliaryChartModel['series']): TrendReversalDatum[] {
  const key = (segmentId: string, index: number) => `${segmentId}:${index}`
  const values = (name: string) => new Map(series.filter(item => item.key === name).flatMap(item => item.points.map(point => [key(point.segmentId, point.index), point.value] as const)))
  const rebound = values('rebound')
  const adjust = values('adjust')
  return series.filter(item => item.key === 'bias').flatMap(item => item.points).sort((a, b) => a.index - b.index).map(point => ({
    index: point.index, segmentId: point.segmentId, time: point.time, bias: point.value,
    rebound: rebound.get(key(point.segmentId, point.index)) ?? 0,
    adjust: adjust.get(key(point.segmentId, point.index)) ?? 0,
  }))
}

export interface TrendReversalDrawItem {
  readonly kind: 'axis' | 'bar'
  readonly color: string
  readonly x?: number
  readonly width?: number
  readonly y: number
  readonly height: number
}

export function buildNewowTrendReversalCommands(data: readonly TrendReversalDatum[], width: number, height: number,
  xOf: (time: Time) => number | null, topInset = 72): { items: readonly TrendReversalDrawItem[]; limit: number; zeroY: number } {
  const visible = data.map(item => ({ item, x: xOf(item.time) })).filter((point): point is { item: TrendReversalDatum; x: number } => point.x !== null && point.x >= 0 && point.x <= width)
  const usable = Math.max(1, height - topInset - 22)
  const zeroY = topInset + usable * 0.62
  const limit = Math.max(1, Math.ceil(Math.max(0, ...visible.map(point => Math.abs(point.item.bias))) * 1.1))
  const step = Math.min(...visible.slice(1).map((point, index) => point.x - visible[index]!.x).filter(gap => gap > 0), width / Math.max(visible.length, 1))
  const barWidth = Math.max(2, Math.min(18, step * 0.72))
  const items: TrendReversalDrawItem[] = [{ kind: 'axis', color: NEWOW_TREND_REVERSAL_STYLE.axis, y: zeroY, height: 0 }]
  for (const { item, x } of visible) {
    const positive = item.bias >= 0
    const availableHeight = positive ? zeroY - topInset : height - 22 - zeroY
    const barHeight = Math.max(0.7, Math.abs(item.bias) / limit * availableHeight)
    const color = item.adjust !== 0 ? NEWOW_TREND_REVERSAL_STYLE.adjust
      : item.rebound !== 0 ? NEWOW_TREND_REVERSAL_STYLE.rebound
      : positive ? NEWOW_TREND_REVERSAL_STYLE.positive : NEWOW_TREND_REVERSAL_STYLE.negative
    items.push({ kind: 'bar', color, x, width: barWidth, y: positive ? zeroY - barHeight : zeroY, height: barHeight })
  }
  return { items, limit, zeroY }
}

export class NewowTrendReversalPrimitive implements ISeriesPrimitive<Time> {
  private attachment: SeriesAttachedParameter<Time> | null = null
  private data: readonly TrendReversalDatum[] = []
  private topInset = 72
  private readonly view: IPrimitivePaneView = { zOrder: () => 'top', renderer: () => ({ draw: target => this.draw(target) }) }
  attached(value: SeriesAttachedParameter<Time>): void { this.attachment = value }
  detached(): void { this.attachment = null; this.data = [] }
  paneViews(): readonly IPrimitivePaneView[] { return [this.view] }
  setData(data: readonly TrendReversalDatum[], topInset = 72): void { this.data = data; this.topInset = topInset; this.attachment?.requestUpdate() }
  updateAllViews(): void {}

  private draw(target: Parameters<IPrimitivePaneRenderer['draw']>[0]): void {
    if (!this.attachment || !this.data.length) return
    target.useMediaCoordinateSpace(({ context, mediaSize }) => {
      const { items, limit } = buildNewowTrendReversalCommands(this.data, mediaSize.width, mediaSize.height,
        time => this.attachment!.chart.timeScale().timeToCoordinate(time), this.topInset)
      context.save()
      for (const item of items) {
        context.fillStyle = item.color
        if (item.kind === 'axis') context.fillRect(0, item.y, mediaSize.width, 1)
        else context.fillRect(item.x! - item.width! / 2, item.y, item.width!, item.height)
      }
      context.fillStyle = NEWOW_TREND_REVERSAL_STYLE.axis
      context.font = '10px -apple-system, sans-serif'
      context.textAlign = 'left'; context.fillText('0', 4, mediaSize.height - 5)
      context.textAlign = 'right'; context.fillText(`+${limit.toFixed(1)}% / −${limit.toFixed(1)}%`, mediaSize.width - 5, mediaSize.height - 5)
      context.restore()
    })
  }
}
