import type { IPrimitivePaneRenderer, IPrimitivePaneView, ISeriesPrimitive, SeriesAttachedParameter, Time } from 'lightweight-charts'

export const NEWOW_UP_DOWN_ENERGY_STYLE = {
  up: '#d32f2f', down: '#388e3c', reference: '#4a90d9',
  band: '#ff3b30', rebound: '#ff9500', oversold: '#e040fb',
} as const

interface EnergyPoint {
  readonly index: number
  readonly barEnd: string
  readonly physicalContract: string
  readonly segmentId: string
  readonly time: Time
  readonly value: number
}

interface EnergySeries { readonly key: string; readonly points: readonly EnergyPoint[] }
interface EnergyBar { readonly barEnd: string; readonly physicalContract: string; readonly calculationSegmentId: string; readonly close: number }

export interface NewowUpDownEnergyDatum {
  readonly index: number
  readonly segmentId: string
  readonly time: Time
  readonly value: number
  readonly previous: number | null
  readonly risingColor: boolean
  readonly signal: 'band' | 'rebound' | 'oversold' | null
}

/** Joins the server's formula values with the aligned, same-owner close used by the original color rule. */
export function buildNewowUpDownEnergyData(series: readonly EnergySeries[], bars: readonly EnergyBar[]): NewowUpDownEnergyDatum[] {
  const byBar = new Map(bars.map(bar => [`${bar.physicalContract}:${bar.calculationSegmentId}:${bar.barEnd}`, bar]))
  const byKey = (key: string): Map<string, number> => new Map(series.filter(item => item.key === key).flatMap(item => item.points.map(point => [`${point.segmentId}:${point.index}`, point.value] as const)))
  const ma10 = byKey('ma10')
  const band = byKey('band_entry')
  const rebound = byKey('rebound_entry')
  const oversold = byKey('oversold_entry')
  const values = series.filter(item => item.key === 'var4').flatMap(item => item.points).sort((left, right) => left.index - right.index)
  const result: NewowUpDownEnergyDatum[] = []
  let previous: EnergyPoint | null = null
  for (const point of values) {
    const close = byBar.get(`${point.physicalContract}:${point.segmentId}:${point.barEnd}`)?.close
    const average = ma10.get(`${point.segmentId}:${point.index}`)
    if (close === undefined || average === undefined) { previous = null; continue }
    const key = `${point.segmentId}:${point.index}`
    result.push({
      index: point.index, segmentId: point.segmentId, time: point.time, value: point.value,
      previous: previous?.segmentId === point.segmentId && previous.index === point.index - 1 ? previous.value : null,
      risingColor: close >= average,
      signal: band.get(key) === 80 ? 'band' : rebound.get(key) === 80 ? 'rebound' : oversold.get(key) === 80 ? 'oversold' : null,
    })
    previous = point
  }
  return result
}

export interface NewowUpDownEnergyDrawItem {
  readonly kind: 'reference' | 'step' | 'signal'
  readonly color: string
  readonly x?: number
  readonly width?: number
  readonly fromY: number
  readonly toY: number
  readonly text?: string
}

/** Reproduces the retained v3.2.82 drawUpDownEnergy 0–100 pane and signal priority. */
export function buildNewowUpDownEnergyCommands(
  data: readonly NewowUpDownEnergyDatum[], width: number, height: number,
  xOf: (time: Time) => number | null,
  topInset = 72,
): readonly NewowUpDownEnergyDrawItem[] {
  // The controls overlay the pane; reserve their measured height for labels and triangles.
  const padTop = topInset
  const chartHeight = Math.max(0, height - padTop - 15)
  const y = (value: number) => padTop + (105 - value) * chartHeight / 110
  const items: NewowUpDownEnergyDrawItem[] = [{ kind: 'reference', color: NEWOW_UP_DOWN_ENERGY_STYLE.reference, fromY: y(50), toY: y(50) }]
  let previous: NewowUpDownEnergyDatum | null = null
  for (const row of data) {
    const x = xOf(row.time)
    const previousX = previous === null ? null : xOf(previous.time)
    if (row.previous !== null && x !== null && previousX !== null && x >= 0 && previousX <= width) {
      const top = Math.min(y(row.previous), y(row.value))
      items.push({ kind: 'step', color: row.risingColor ? NEWOW_UP_DOWN_ENERGY_STYLE.up : NEWOW_UP_DOWN_ENERGY_STYLE.down,
        x: previousX, width: Math.max(x - previousX, 0.5), fromY: top, toY: top + Math.max(Math.abs(y(row.value) - y(row.previous)), 0.8) })
    }
    previous = row
  }
  // Source canvas paints every label after the stairs, so later bars cannot cover a signal stem.
  let lastSignalX = Number.NEGATIVE_INFINITY
  let lastSignalLane = 0
  for (const row of data) {
    const x = xOf(row.time)
    if (row.signal !== null && x !== null && x >= 0 && x <= width) {
      const signal = row.signal
      const lane = x - lastSignalX < 28 ? 1 - lastSignalLane : 0
      items.push({ kind: 'signal', color: NEWOW_UP_DOWN_ENERGY_STYLE[signal], x, fromY: padTop + 2 + lane * 17, toY: y(50),
        text: { band: '波段', rebound: '反弹', oversold: '超跌' }[signal] })
      lastSignalX = x
      lastSignalLane = lane
    }
  }
  return items
}

export class NewowUpDownEnergyPrimitive implements ISeriesPrimitive<Time> {
  private attachment: SeriesAttachedParameter<Time> | null = null
  private data: readonly NewowUpDownEnergyDatum[] = []
  private topInset = 72
  private readonly view: IPrimitivePaneView = { zOrder: () => 'top', renderer: () => ({ draw: target => this.draw(target) }) }
  attached(value: SeriesAttachedParameter<Time>): void { this.attachment = value }
  detached(): void { this.attachment = null; this.data = [] }
  paneViews(): readonly IPrimitivePaneView[] { return [this.view] }
  setData(data: readonly NewowUpDownEnergyDatum[], topInset = 72): void { this.data = data; this.topInset = topInset; this.attachment?.requestUpdate() }
  updateAllViews(): void {}

  private draw(target: Parameters<IPrimitivePaneRenderer['draw']>[0]): void {
    if (!this.attachment || this.data.length === 0) return
    const attachment = this.attachment
    target.useMediaCoordinateSpace(({ context, mediaSize }) => {
      const items = buildNewowUpDownEnergyCommands(this.data, mediaSize.width, mediaSize.height, time => attachment.chart.timeScale().timeToCoordinate(time), this.topInset)
      context.save()
      for (const item of items) {
        context.strokeStyle = item.color; context.fillStyle = item.color; context.lineWidth = 1
        if (item.kind === 'reference') {
          context.beginPath(); context.moveTo(0, item.fromY); context.lineTo(mediaSize.width, item.toY); context.stroke()
        } else if (item.kind === 'step') {
          context.fillRect(item.x!, item.fromY, item.width!, item.toY - item.fromY)
        } else {
          const x = item.x!; const apex = item.fromY
          context.beginPath(); context.moveTo(x, apex); context.lineTo(x - 7, apex + 11); context.lineTo(x + 7, apex + 11); context.closePath(); context.fill()
          context.font = 'bold 10px -apple-system, sans-serif'; context.textAlign = 'center'; context.textBaseline = 'bottom'
          context.fillText(item.text!, x, apex - 3)
          context.setLineDash([3, 3]); context.beginPath(); context.moveTo(x, apex + 11); context.lineTo(x, item.toY); context.stroke(); context.setLineDash([])
        }
      }
      context.restore()
    })
  }
}
