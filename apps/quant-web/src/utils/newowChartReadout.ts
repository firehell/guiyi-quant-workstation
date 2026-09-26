import type { Time } from 'lightweight-charts'
import type { NewowProductChartModel, NewowAlignedAuxiliaryChartModel } from '../components/market/detail/newow/newowProductChartPrimitives.ts'
import { chartMarkerTime } from '../components/market/detail/newow/newowProductChartPrimitives.ts'

export function newowTimeKey(time: Time): string {
  if (typeof time === 'number') return String(time)
  if (typeof time === 'string') return time
  return `${time.year}-${String(time.month).padStart(2, '0')}-${String(time.day).padStart(2, '0')}`
}
/** Exact time matching only; absence is shown rather than carrying a previous value. */
export function newowChartReadout(model: NewowProductChartModel | null, auxiliary: NewowAlignedAuxiliaryChartModel | null, time: Time | null): string[] {
  if (!model || time === null) return []
  const key = newowTimeKey(time)
  const bar = model.bars.find(item => newowTimeKey(chartMarkerTime(item.barEnd, model.identity.frequency, item.tradingDay)) === key)
  if (!bar) return []
  const number = (value: number) => Number.isFinite(value) ? String(value) : '—'
  const rows = [bar.tradingDay, bar.physicalContract, `开 ${number(bar.open)} 高 ${number(bar.high)} 低 ${number(bar.low)} 收 ${number(bar.close)}`, `量 ${number(bar.volume)}`]
  const labels = new Set((auxiliary?.series ?? []).map(series => series.label))
  for (const label of labels) {
    const points = (auxiliary?.series ?? []).filter(series => series.label === label)
      .flatMap(series => series.points.filter(item => newowTimeKey(item.time) === key))
    rows.push(`${label} ${points.length === 1 ? number(points[0]!.value) : '—（该 Bar 缺值 / 预热）'}`)
  }
  if (!auxiliary) rows.push('副图不可用 / 预热')
  if (auxiliary && rows.length === 4) rows.push('该 Bar 无副图读数 / 预热')
  return rows
}
