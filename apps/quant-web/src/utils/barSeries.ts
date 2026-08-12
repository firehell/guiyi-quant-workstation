import type { BarData } from '../types/market'

/** 按 formal bar end 排序去重；同一 end 后出现的值覆盖前值。 */
export function normalizeBarSeries(items: BarData[]): BarData[] {
  const byEnd = new Map<string, BarData>()
  for (const item of items) byEnd.set(item.time, item)
  return [...byEnd.values()].sort((left, right) => Date.parse(left.time) - Date.parse(right.time))
}
