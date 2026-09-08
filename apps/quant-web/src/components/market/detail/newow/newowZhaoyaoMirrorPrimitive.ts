import type { IPrimitivePaneRenderer, IPrimitivePaneView, ISeriesPrimitive, SeriesAttachedParameter, Time } from 'lightweight-charts'

export const NEWOW_ZHAOYAO_MIRROR_STYLE = {
  zero: '#ffcc00', entry: '#ff3b30', wash: '#34c759', distribution: '#007aff',
  markup: '#ffcc00', exit: '#0066bb', inducement: '#ff8800', caution: '#00FF00',
} as const

export interface NewowZhaoyaoMirrorDatum {
  readonly time: Time
  readonly entry: number
  readonly wash: number
  readonly distribution: number
  readonly markup: number
  readonly exit: number
  readonly inducement: number
  readonly caution: number
}

interface MirrorSourceSeries {
  readonly key: string
  readonly points: readonly { readonly index: number; readonly time: Time; readonly value: number }[]
}

/** Joins server-owned split series without collapsing repeated keys from later physical segments. */
export function buildNewowZhaoyaoMirrorData(series: readonly MirrorSourceSeries[]): NewowZhaoyaoMirrorDatum[] {
  type MutableRow = { time: Time; entry: number; wash: number; distribution: number; markup: number; exit: number; inducement: number; caution: number }
  const rows = new Map<number, MutableRow>()
  const allowed = new Set(['entry', 'wash', 'distribution', 'markup', 'exit', 'inducement', 'caution'])
  for (const source of series) {
    if (!allowed.has(source.key)) continue
    for (const point of source.points) {
      let row = rows.get(point.index)
      if (!row) {
        row = { time: point.time, entry: 0, wash: 0, distribution: 0, markup: 0, exit: 0, inducement: 0, caution: 0 }
        rows.set(point.index, row)
      }
      row[source.key as keyof Omit<MutableRow, 'time'>] = point.value
    }
  }
  return [...rows.entries()].sort(([left], [right]) => left - right).map(([, row]) => ({ ...row }))
}

type MirrorKind = 'zero' | 'entry' | 'wash' | 'distribution' | 'markup' | 'exit' | 'inducement' | 'caution'
export interface NewowZhaoyaoMirrorDrawItem {
  readonly kind: MirrorKind
  readonly color: string
  readonly x?: number
  readonly width?: number
  readonly fromY: number
  readonly toY: number
  readonly dash?: readonly number[]
  readonly text?: string
}
export interface NewowZhaoyaoMirrorCommands {
  readonly zeroY: number
  readonly barWidth: number
  readonly items: readonly NewowZhaoyaoMirrorDrawItem[]
}

/** Projects the frozen v3.2.82 drawZhaoyaoMirror canvas rules without deriving any formula values. */
export function buildNewowZhaoyaoMirrorCommands(
  data: readonly NewowZhaoyaoMirrorDatum[], width: number, height: number,
  xOf: (time: Time) => number | null,
): NewowZhaoyaoMirrorCommands {
  const visible = data.map(row => ({ row, x: xOf(row.time) })).filter((item): item is { row: NewowZhaoyaoMirrorDatum; x: number } => item.x !== null && item.x >= 0 && item.x <= width)
  const padTop = 10
  const chartHeight = Math.max(0, height - padTop - 15)
  const zeroY = padTop + chartHeight * 0.48
  const maxUp = Math.max(0.001, ...visible.flatMap(({ row }) => [row.entry || 0, row.wash || 0, row.exit || 0, row.inducement || 0]))
  const maxDown = Math.max(0.001, ...visible.flatMap(({ row }) => [row.markup || 0, row.distribution || 0]))
  const up = (value: number) => zeroY - value * (chartHeight * 0.48 / maxUp)
  const down = (value: number) => zeroY + value * (chartHeight * 0.52 / maxDown)
  const gaps = visible.slice(1).map((item, index) => Math.abs(item.x - visible[index]!.x)).filter(gap => gap > 0)
  const barWidth = Math.max(2, (gaps.length ? Math.min(...gaps) : 8) * 0.65)
  const narrowWidth = Math.max(1, barWidth * 0.45)
  const items: NewowZhaoyaoMirrorDrawItem[] = [{ kind: 'zero', color: NEWOW_ZHAOYAO_MIRROR_STYLE.zero, fromY: zeroY, toY: zeroY, dash: [4, 3] }]
  const bars = (keys: readonly ('entry' | 'markup' | 'wash' | 'distribution')[], bar: number) => {
    for (const { row, x } of visible) for (const key of keys) {
      const value = row[key]
      if (!(value > 0)) continue
      const upper = key === 'entry' || key === 'wash'
      items.push({ kind: key, color: NEWOW_ZHAOYAO_MIRROR_STYLE[key], x, width: bar, fromY: upper ? up(value) : zeroY, toY: upper ? zeroY : down(value) })
    }
  }
  bars(['entry', 'markup'], barWidth)
  bars(['wash', 'distribution'], narrowWidth)
  for (const { row, x } of visible) {
    if (row.exit > 0) items.push({ kind: 'exit', color: NEWOW_ZHAOYAO_MIRROR_STYLE.exit, x, fromY: up(row.exit), toY: zeroY, dash: [2, 2] })
    if (row.inducement > 0) items.push({ kind: 'inducement', color: NEWOW_ZHAOYAO_MIRROR_STYLE.inducement, x, fromY: zeroY, toY: down(row.inducement), dash: [2, 2] })
  }
  for (const { row, x } of visible) if (row.caution === 50) {
    items.push({ kind: 'caution', color: NEWOW_ZHAOYAO_MIRROR_STYLE.caution, x, fromY: padTop + 2, toY: zeroY, dash: [3, 3], text: '小 心' })
  }
  return { zeroY, barWidth, items }
}

export class NewowZhaoyaoMirrorPrimitive implements ISeriesPrimitive<Time> {
  private attachment: SeriesAttachedParameter<Time> | null = null
  private data: readonly NewowZhaoyaoMirrorDatum[] = []
  private readonly view: IPrimitivePaneView = { zOrder: () => 'top', renderer: () => ({ draw: target => this.draw(target) }) }
  attached(value: SeriesAttachedParameter<Time>): void { this.attachment = value }
  detached(): void { this.attachment = null; this.data = [] }
  paneViews(): readonly IPrimitivePaneView[] { return [this.view] }
  setData(data: readonly NewowZhaoyaoMirrorDatum[]): void { this.data = data; this.attachment?.requestUpdate() }
  updateAllViews(): void {}

  private draw(target: Parameters<IPrimitivePaneRenderer['draw']>[0]): void {
    if (!this.attachment || this.data.length === 0) return
    const attachment = this.attachment
    target.useMediaCoordinateSpace(({ context, mediaSize }) => {
      const projected = buildNewowZhaoyaoMirrorCommands(this.data, mediaSize.width, mediaSize.height, time => attachment.chart.timeScale().timeToCoordinate(time))
      context.save()
      for (const item of projected.items) drawItem(context, item, mediaSize.width)
      context.restore()
    })
  }
}

function drawItem(context: CanvasRenderingContext2D, item: NewowZhaoyaoMirrorDrawItem, paneWidth: number): void {
  context.strokeStyle = item.color; context.fillStyle = item.color
  context.lineWidth = item.kind === 'zero' ? 1.2 : 1
  context.setLineDash(item.dash ? [...item.dash] : [])
  if (item.kind === 'zero') {
    context.beginPath(); context.moveTo(0, item.fromY); context.lineTo(paneWidth, item.toY); context.stroke()
  } else if (item.kind === 'entry' || item.kind === 'wash' || item.kind === 'distribution' || item.kind === 'markup') {
    context.fillRect(item.x! - item.width! / 2, item.fromY, item.width!, item.toY - item.fromY)
  } else if (item.kind === 'caution') {
    const apexY = item.fromY
    context.beginPath(); context.moveTo(item.x!, apexY); context.lineTo(item.x! - 6, apexY + 10); context.lineTo(item.x! + 6, apexY + 10); context.closePath(); context.fill()
    context.font = 'bold 10px -apple-system, sans-serif'; context.textAlign = 'center'; context.textBaseline = 'bottom'; context.fillText(item.text!, item.x!, apexY - 3)
    context.beginPath(); context.moveTo(item.x!, apexY + 10); context.lineTo(item.x!, item.toY); context.stroke()
  } else {
    context.beginPath(); context.moveTo(item.x!, item.fromY); context.lineTo(item.x!, item.toY); context.stroke()
  }
  context.setLineDash([])
}
