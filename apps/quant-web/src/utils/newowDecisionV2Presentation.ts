import type { Cdv2 } from '../types/newowDecisionV2'

type Fact = Cdv2['facts'][number]
const roles: Record<string, string> = {
  trend_day: '日线趋势', oscillation_day: '日线震荡',
  trend_week: '周线趋势', oscillation_week: '周线震荡',
  trend_m60: '60分钟趋势', oscillation_m60: '60分钟震荡',
}
export const decisionRoleLabel = (role: string) => roles[role] ?? role
const stateLabels: Record<string, string> = { buy: '建仓', hold: '持有', sell: '清仓', wait: '空仓' }
export const decisionStateLabel = (state: string | null | undefined) => stateLabels[state ?? ''] ?? '未知'
export function decisionFactState(fact: Fact | undefined): string {
  if (fact?.role.endsWith('_m60')) return '未参与'
  return fact?.status === 'ready' ? decisionStateLabel(fact.state) : '状态不可用'
}
export function decisionFactAge(fact: Fact | undefined): string {
  if (fact?.role.endsWith('_m60')) return '未参与计龄'
  if (fact?.status !== 'ready' || fact.age < 0) return '计龄未知'
  const unit = fact.frequency === '1w' ? '周K' : fact.frequency === '1d' ? '日K' : ''
  return unit ? `${fact.age} 根${unit}` : '计龄未知'
}
export function decisionFactReason(fact: Fact | undefined): string {
  if (fact?.role.endsWith('_m60')) return '60分钟未参与本卡计算'
  if (fact?.status === 'ready') return '已完成 K 线策略回放'
  return '输入预热、数据或合约上下文不足；不使用其他周期替代'
}
const biasLabels: Record<string, string> = {
  bullish: '偏多', bearish: '偏空', cautious: '谨慎', warning: '反弹警示', neutral: '中性',
}
// Explain the authoritative reported code; do not reproduce the scoring or mismatch judge in the UI.
export function decisionResonanceReason(cd: Cdv2): string {
  const reasons: Record<string, string> = {
    R4: '趋势与震荡基调同向，且各自至少两个明确周期同向；本卡仅为日周确认，不包含60分钟确认。',
    R3: '趋势与震荡基调同向，但未满足两组内部均至少两个明确周期同向。',
    R2: cd.mismatch ? `命中 ${cd.mismatch} 错配，按现行规则归入 R2。` : '趋势基调中性，震荡节奏有明确方向，按现行规则归入 R2。',
    R1: ['cautious', 'warning'].includes(cd.trend_bias)
      ? '趋势处于谨慎／反弹警示，震荡方向明确，按现行规则归入 R1。'
      : '趋势与震荡方向相反，按现行规则归入 R1。',
    R0: '未满足 R1–R4 条件，暂未形成明确共振。',
  }
  return `趋势基调${biasLabels[cd.trend_bias] ?? '未知'} · 震荡节奏${biasLabels[cd.oscillation_bias] ?? '未知'}。${reasons[cd.resonance] ?? '共振依据未知。'}`
}
export function decisionMismatchReason(cd: Cdv2): string {
  const reasons: Record<string, string> = {
    MM1: '日线趋势向上，日线震荡已清仓至少3根日K，且没有新鲜趋势卖出信号。',
    MM2: '日线趋势向下，日线震荡仍持有至少3根日K；没有新鲜趋势买入信号，且趋势基调不是偏空。',
    MM3: '日线趋势出现新鲜卖出信号（0–2根日K），日线震荡仍持有。',
    MM4: '日线趋势出现新鲜买入信号（0–2根日K），日线震荡已清仓。',
  }
  if (!cd.mismatch) return '未命中 MM1–MM4 错配规则；输入缺失时不代表已确认无冲突。'
  const source = cd.mismatch === 'MM3' || cd.mismatch === 'MM4' ? '日线趋势穿越信号' : '日线震荡最近动作'
  const age = cd.mismatch_age >= 0 ? `${cd.mismatch_age} 根日K` : '计龄未知'
  return `${reasons[cd.mismatch] ?? '错配依据未知。'}错配计龄来自${source}：${age}。`
}
