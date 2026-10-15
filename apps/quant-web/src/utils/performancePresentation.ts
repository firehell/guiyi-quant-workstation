/** Display statistics only. Never a strategy, fill, or account authority. */
export const PERFORMANCE_PRESENTATION_VERSION = 'guiyi_performance_presentation_v1'
export type PerformanceUnit = 'percent' | 'percentage_points' | 'currency'
export interface PerformanceIdentity {
  kind: 'page' | 'closed' | 'holding' | 'account'
  unit: PerformanceUnit
  since: string
  through: string
  cutoff: string
  version: string
  coverage: string
  membership: string
}
export function annualizedReference({ start, end, days }: {start:number;end:number;days:number}): number | null {
  if (![start,end,days].every(Number.isFinite) || days <= 0 || start <= -100 || end <= -100) return null
  const value = (Math.pow((100 + end) / (100 + start), 365 / days) - 1) * 100
  return Number.isFinite(value) ? value : null
}
export const metricUnit = (unit: PerformanceUnit): string => ({percent:'%',percentage_points:'百分点',currency:'元'})[unit]
export const performanceDrawdownLabel = (kind:'page'|'reference'|'account'|'loss'): string => ({page:'页面曲线回撤（百分点）',reference:'参考权益比例回撤',account:'模型账户回撤',loss:'单笔最大亏损'})[kind]
