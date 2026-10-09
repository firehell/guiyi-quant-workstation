import type { DailyWeeklyPathPeriod, DecisionPriceSource } from '../types/newowDecisionV2.ts'

export function dailyWeeklyPathGeometry(periods: DailyWeeklyPathPeriod[]) {
  const value = (source: DecisionPriceSource | null) => {
    const raw = source ? Number(source.raw) : NaN
    return Number.isFinite(raw) && raw > 0 ? raw : null
  }
  const all = periods.flatMap(p => [value(p.cost), value(p.current), value(p.target)]).filter((n): n is number => n !== null)
  const min = all.length ? Math.min(...all) : 0, max = all.length ? Math.max(...all) : 0
  const point = (source: DecisionPriceSource | null, x: number) => {
    const n = value(source)
    return n === null ? null : { x, y: max === min ? 200 : 340 - (n - min) / (max - min) * 290 }
  }
  return periods.map(p => ({
    ...p, label: p.frequency === '1w' ? '周线' : p.frequency === '60m' ? '60分' : '日线', color: p.frequency === '1w' ? '#ef365c' : p.frequency === '60m' ? '#00a6b8' : '#ff9500',
    dash: p.state === 'buy' || p.state === 'hold' ? undefined : p.state === 'sell' ? '7 5' : '2 5',
    stateLabel: p.state === 'buy' ? '建仓' : p.state === 'hold' ? '持有' : p.state === 'sell' ? '清仓' : p.state === 'wait' ? '空仓' : '数据不足',
    active: p.state === 'buy' || p.state === 'hold',
    cost: point(p.cost, 75), current: point(p.current, 471.8), target: point(p.target, 715),
  }))
}
