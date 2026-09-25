import type { IPrimitivePaneRenderer, IPrimitivePaneView, ISeriesPrimitive, SeriesAttachedParameter, Time } from 'lightweight-charts'
import type { NewowAlignedAuxiliaryChartModel } from './newowProductChartPrimitives'
import type { NewowAuxiliarySegment } from '@/types/newowProduct'

export const NEWOW_MAIN_FORCE_STYLE = {
  start: '#9933ff', controlled: '#ff0000', high: '#ff00ff', distribution: '#00ff00', none: '#ffcc66', reference: '#4a90d9',
} as const

type ControlStatus = '开始控盘' | '有庄控盘' | '高度控盘' | '主力出货' | '无庄控盘' | '高控+出货'
const STATUSES = new Set<ControlStatus>(['开始控盘', '有庄控盘', '高度控盘', '主力出货', '无庄控盘', '高控+出货'])

export interface MainForceDatum {
  readonly index: number
  readonly segmentId: string
  readonly time: Time
  readonly value: number
  readonly previous: number | null
  readonly status: ControlStatus
}

/** Preserve the server's status for its exact aligned point; never infer a status from the plotted value. */
export function buildNewowMainForceData(series: NewowAlignedAuxiliaryChartModel['series'], segments: readonly NewowAuxiliarySegment[]): MainForceDatum[] {
  const statusByPoint = new Map<string, string>()
  let offset = 0
  for (const segment of segments) {
    if (segment.data !== null && !Array.isArray(segment.data) && 'status' in segment.data && Array.isArray(segment.data.status)) {
      segment.data.status.forEach((status, index) => statusByPoint.set(`${segment.segment_id}:${offset + index}`, status))
    }
    offset += segment.bar_ends.length
  }
  const result: MainForceDatum[] = []
  let previous: { index: number; segmentId: string; value: number } | null = null
  for (const point of series.filter(item => item.key === 'kongpan').flatMap(item => item.points).sort((a, b) => a.index - b.index)) {
    const status = statusByPoint.get(`${point.segmentId}:${point.index}`)
    if (!STATUSES.has(status as ControlStatus)) { previous = null; continue }
    result.push({ index: point.index, segmentId: point.segmentId, time: point.time, value: point.value,
      previous: previous !== null && previous.segmentId === point.segmentId && previous.index === point.index - 1 ? previous.value : null,
      status: status as ControlStatus })
    previous = point
  }
  return result
}

export interface MainForceDrawItem {
  readonly kind: 'reference' | 'bar' | 'start'
  readonly color: string
  readonly x?: number
  readonly width?: number
  readonly fromY: number
  readonly toY: number
  readonly splitY?: number
}

/** Page formula: normalize by the maximum absolute KONGPAN across the loaded window, then center zero at 50. */
export function buildNewowMainForceCommands(data: readonly MainForceDatum[], width: number, height: number,
  xOf: (time: Time) => number | null, topInset = 72): readonly MainForceDrawItem[] {
  const chartHeight = Math.max(0, height - topInset - 15)
  const y = (displayValue: number) => topInset + (105 - displayValue) * chartHeight / 110
  const zeroY = y(50)
  const absMax = Math.max(...data.map(item => Math.abs(item.value))) || 1
  const visible = data.map(item => ({ item, x: xOf(item.time) })).filter((point): point is { item: MainForceDatum; x: number } => point.x !== null && point.x >= 0 && point.x <= width)
  const gaps = visible.slice(1).map((point, index) => point.x - visible[index]!.x).filter(gap => gap > 0)
  const barWidth = Math.max(2, (gaps.length ? Math.min(...gaps) : width / Math.max(data.length, 1)) * 0.75)
  const items: MainForceDrawItem[] = [{ kind: 'reference', color: NEWOW_MAIN_FORCE_STYLE.reference, fromY: zeroY, toY: zeroY }]
  for (const { item, x } of visible) {
    if (item.status === '开始控盘') {
      items.push({ kind: 'start', color: NEWOW_MAIN_FORCE_STYLE.start, x, fromY: topInset + 2, toY: zeroY })
      continue
    }
    const valueY = y(50 + item.value / absMax * 50)
    const fromY = Math.min(valueY, zeroY)
    const toY = Math.max(valueY, zeroY)
    const color = item.status === '有庄控盘' ? NEWOW_MAIN_FORCE_STYLE.controlled
      : item.status === '高度控盘' ? NEWOW_MAIN_FORCE_STYLE.high
      : item.status === '主力出货' || item.status === '高控+出货' ? NEWOW_MAIN_FORCE_STYLE.distribution
      : NEWOW_MAIN_FORCE_STYLE.none
    const ratio = item.status === '高控+出货'
      ? Math.abs(item.value) / (Math.abs(item.value) + (Math.abs(item.previous ?? 0) || 1)) : null
    items.push({ kind: 'bar', color, x, width: barWidth, fromY, toY,
      splitY: ratio === null ? undefined : valueY + (toY - valueY) * (1 - ratio) })
  }
  return items
}

export class NewowMainForceControlPrimitive implements ISeriesPrimitive<Time> {
  private attachment: SeriesAttachedParameter<Time> | null = null
  private data: readonly MainForceDatum[] = []
  private topInset = 72
  private readonly view: IPrimitivePaneView = { zOrder: () => 'top', renderer: () => ({ draw: target => this.draw(target) }) }
  attached(value: SeriesAttachedParameter<Time>): void { this.attachment = value }
  detached(): void { this.attachment = null; this.data = [] }
  paneViews(): readonly IPrimitivePaneView[] { return [this.view] }
  setData(data: readonly MainForceDatum[], topInset = 72): void { this.data = data; this.topInset = topInset; this.attachment?.requestUpdate() }
  updateAllViews(): void {}

  private draw(target: Parameters<IPrimitivePaneRenderer['draw']>[0]): void {
    if (!this.attachment || this.data.length === 0) return
    target.useMediaCoordinateSpace(({ context, mediaSize }) => {
      const items = buildNewowMainForceCommands(this.data, mediaSize.width, mediaSize.height,
        time => this.attachment!.chart.timeScale().timeToCoordinate(time), this.topInset)
      context.save()
      for (const item of items) {
        context.fillStyle = item.color; context.strokeStyle = item.color; context.lineWidth = 1
        if (item.kind === 'reference') {
          context.beginPath(); context.moveTo(0, item.fromY); context.lineTo(mediaSize.width, item.toY); context.stroke()
        } else if (item.kind === 'start') {
          const x = item.x!; const apex = item.fromY
          context.beginPath(); context.moveTo(x, apex); context.lineTo(x - 6, apex + 10); context.lineTo(x + 6, apex + 10); context.closePath(); context.fill()
          context.font = 'bold 10px -apple-system, sans-serif'; context.textAlign = 'center'; context.textBaseline = 'bottom'
          context.fillText('开始', x, apex - 3)
          context.setLineDash([3, 3]); context.beginPath(); context.moveTo(x, apex + 10); context.lineTo(x, item.toY); context.stroke(); context.setLineDash([])
        } else if (item.splitY !== undefined) {
          const x = item.x! - item.width! / 2
          context.fillStyle = NEWOW_MAIN_FORCE_STYLE.distribution
          context.fillRect(x, item.fromY, item.width!, item.splitY - item.fromY)
          context.fillStyle = NEWOW_MAIN_FORCE_STYLE.high
          context.fillRect(x, item.splitY, item.width!, item.toY - item.splitY)
          context.strokeStyle = '#fff'; context.beginPath(); context.moveTo(x, item.splitY); context.lineTo(x + item.width!, item.splitY); context.stroke()
        } else {
          context.fillRect(item.x! - item.width! / 2, item.fromY, item.width!, Math.max(item.toY - item.fromY, 0.8))
        }
      }
      context.restore()
    })
  }
}
