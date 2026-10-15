/** Geometry only: callers supply authoritative dates and segment identities. */
export interface ReturnCurvePoint {
  value: number | null
  date: string
  segment: string
  position: number
}
export interface ReturnCurvePolicy {
  valueUnit?: 'currency' | 'percent' | 'percentage_points'
  headroom: number
  singlePoint?: 'start' | 'end'
  areaBaseline: 'zero' | 'bottom'
  start?: number
  end?: number
  extend?: boolean
  dateTicks?: 'points' | 'calendar-window'
}
interface PositionedPoint { x: number; y: number }
interface DateTick { x: number; day: string; label: string; anchor: string }

export function returnCurveLayout<T extends ReturnCurvePoint>(source: readonly T[], policy: ReturnCurvePolicy) {
  const empty = (message: string | null) => ({
    points: [] as (T & PositionedPoint)[],
    segments: [] as string[],
    areas: [] as string[],
    levels: [] as { y: number; label: string }[],
    ticks: [] as DateTick[],
    zero: 140,
    low: 0,
    high: 1,
    message,
  })
  const invalid = source.some((point, index) => {
    const date = /^\d{4}-\d{2}-\d{2}$/.test(point.date) ? Date.parse(point.date) : NaN
    return !Number.isFinite(point.position) || !Number.isFinite(date)
      || new Date(date).toISOString().slice(0, 10) !== point.date || !point.segment
      || (index > 0 && point.position < source[index - 1]!.position)
      || (point.value !== null && !Number.isFinite(point.value))
  })
  if (invalid) return empty('曲线日期、数值或区段事实不完整，暂不绘制曲线。')
  const valid = source.filter((point): point is T & { value: number } => point.value !== null)
  if (!valid.length) return empty(null)
  const start = policy.start ?? valid[0]!.position
  const end = policy.end ?? valid.at(-1)!.position
  if (!Number.isFinite(start) || !Number.isFinite(end) || end < start
    || !Number.isFinite(policy.headroom) || policy.headroom < 1) {
    return empty('曲线坐标窗口无效，暂不绘制曲线。')
  }
  let low = 0, high = 0
  for (const point of valid) {
    low = Math.min(low, point.value)
    high = Math.max(high, point.value)
  }
  low *= policy.headroom
  high = high * policy.headroom || (low < 0 ? 0 : 1)
  const y = (value: number) => 140 - (value - low) / (high - low) * 140
  const x = (position: number) => Math.max(0, Math.min(712,
    (end === start ? policy.singlePoint === 'start' ? 0 : 1 : (position - start) / (end - start)) * 712))
  const points: (T & PositionedPoint)[] = []
  const parts: (typeof points)[] = []
  let previous: T | null = null
  for (const point of source) {
    if (point.value === null) {
      previous = null
      continue
    }
    const plotted = { ...point, x: x(point.position), y: y(point.value) }
    if (previous === null || previous.segment !== point.segment) parts.push([])
    parts.at(-1)!.push(plotted)
    points.push(plotted)
    previous = point
  }
  const baseline = policy.areaBaseline === 'zero' ? y(0) : 140
  const segments = parts.map((part, index) => {
    const pairs = part.map(point => `${point.x},${point.y}`)
    if (policy.extend && index === 0) pairs.unshift(`0,${y(0)}`)
    if (policy.extend && index === parts.length - 1) pairs.push(`712,${part.at(-1)!.y}`)
    return pairs.join(' ') + ' '
  })
  const areas = segments.map(segment => {
    const pairs = segment.trim().split(' ')
    return `${pairs[0]!.split(',')[0]},${baseline} ${segment}${pairs.at(-1)!.split(',')[0]},${baseline}`
  })
  const count = Math.min(7, points.length)
  const tickPoints = Array.from({ length: count }, (_, index) =>
    points[Math.round(index * (points.length - 1) / Math.max(1, count - 1))]!)
  let ticks: DateTick[] = tickPoints.filter((point, index) => index === 0 || point.x !== tickPoints[index - 1]!.x)
    .map((point, index, all) => ({
      x: point.x, day: point.date, label: point.date.slice(5),
      anchor: all.length === 1 || index === all.length - 1 ? 'end' : index === 0 ? 'start' : 'middle',
    }))
  if (policy.dateTicks === 'calendar-window') {
    const count = Math.min(7, Math.floor((end - start) / 86400000) + 1)
    ticks = Array.from({ length: count }, (_, index) => {
      const ratio = count === 1 ? 1 : index / (count - 1)
      const day = new Date(start + (end - start) * ratio).toISOString().slice(0, 10)
      return {
        x: ratio * 712, day, label: day.slice(5),
        anchor: count === 1 || index === count - 1 ? 'end' : index === 0 ? 'start' : 'middle',
      }
    })
  }
  return {
    points, segments, areas, zero: y(0), low, high, ticks, message: null,
    levels: Array.from({ length: 5 }, (_, index) => ({
      y: index * 35, label: `${(high - (high - low) * index / 4).toFixed(1)}${policy.valueUnit === 'currency' ? '元' : policy.valueUnit === 'percentage_points' ? 'pp' : '%'}`,
    })),
  }
}

interface CompletedTradePoint {
  value: number
  trade: {
    exit_trading_day?: string | null
    physical_contract: string
    segment_id?: string
    calculation_segment_id?: string
  }
}
/** Completed trades use exit_trading_day, never a timestamp's civil date (night sessions differ). */
export function referenceReturnLayout<T extends CompletedTradePoint>(points: readonly T[], since: string, through: string) {
  return returnCurveLayout(points.map(point => ({
    ...point,
    date: point.trade.exit_trading_day ?? '',
    position: Date.parse(point.trade.exit_trading_day ?? ''),
    segment: JSON.stringify([point.trade.physical_contract, point.trade.segment_id, point.trade.calculation_segment_id]),
  })), {
    headroom: 1.1, areaBaseline: 'zero', valueUnit:'percentage_points', start: Date.parse(since), end: Date.parse(through),
    extend: true, dateTicks: 'calendar-window',
  })
}
