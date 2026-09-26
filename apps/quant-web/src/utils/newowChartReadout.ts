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
  for (const series of auxiliary?.series ?? []) {
    const point = series.points.find(item => newowTimeKey(item.time) === key)
    if (point) rows.push(`${series.label} ${number(point.value)}`)
  }
  if (auxiliary && rows.length === 4) rows.push('该 Bar 无副图读数 / 预热')
  return rows
}
