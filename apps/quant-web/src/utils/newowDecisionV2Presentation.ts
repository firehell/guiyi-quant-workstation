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
  return fact?.status === 'ready' ? decisionStateLabel(fact.state) : '状态不可用'
}
export function decisionFactAge(fact: Fact | undefined): string {
  if (fact?.status !== 'ready' || fact.age < 0) return '计龄未知'
  const unit = fact.frequency === '1w' ? '周K' : fact.frequency === '1d' ? '日K' : fact.frequency === '60m' ? '60分钟K' : ''
  return unit ? `${fact.age} 根${unit}` : '计龄未知'
}
export function decisionFactReason(fact: Fact | undefined): string {
  if (fact?.status === 'ready') return '已完成 K 线策略回放'
  return '输入预热、数据或合约上下文不足；不使用其他周期替代'
}
const biasLabels: Record<string, string> = {
  bullish: '偏多', bearish: '偏空', cautious: '谨慎', warning: '反弹警示', neutral: '中性',
}
// Explain the authoritative reported code; do not reproduce the scoring or mismatch judge in the UI.
export function decisionResonanceReason(cd: Cdv2): string {
  const reasons: Record<string, string> = {
    R4: '趋势与震荡基调同向，且各自至少两个明确周期同向；参与周期以已完成事实列表为准。',
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

const colors = { red: '#ff3b30', green: '#34c759', orange: '#ff9500', warning: '#ff6b35', gray: '#8e8e93' }
export function decisionTier(total: number) {
  if (!Number.isFinite(total) || total < 0 || total > 100) return { label: '评分不可用', color: colors.gray }
  if (total >= 80) return { label: '高确定性', color: colors.red }
  if (total >= 60) return { label: '中等确定性', color: colors.orange }
  if (total >= 40) return { label: '低确定性', color: colors.warning }
  return { label: '信号不足', color: colors.gray }
}
export function decisionVolatility(cd: Cdv2) {
  // Number is only a bounded CSS position. The reported Decimal value/level stay authoritative.
  if (cd.volatility_pct === null || !/^\d+(?:\.\d+)?$/.test(cd.volatility_pct)) return null
  const value = Number(cd.volatility_pct)
  if (!Number.isFinite(value)) return null
  const level = cd.volatility_level
  if (level !== 'low' && level !== 'mid' && level !== 'high') return null
  return { value: cd.volatility_pct, level, label: { low: '低', mid: '中', high: '高' }[level],
    color: { low: colors.green, mid: colors.orange, high: colors.red }[level], position: Math.max(3, Math.min(97, Math.round(value / 6 * 100))) }
}
export function decisionDisplay(cd: Cdv2) {
  const tier = decisionTier(cd.total)
  const resonanceTable: Record<string, { name: string; count: number; color: string }> = {
    R4: { name: '双螺旋共振', count: 5, color: colors.green },
    R3: { name: '基调共振', count: 3, color: colors.orange },
    R2: { name: '错配预警', count: 2, color: colors.warning },
    R1: { name: '信号背离', count: 1, color: colors.red },
    R0: { name: '数据不足', count: 0, color: colors.gray },
  }
  const r = resonanceTable[cd.resonance] ?? { name: '共振未知', count: 0, color: colors.gray }
  const mismatchTable: Record<string, { name: string; color: string }> = {
    MM1: { name: '错配期·逃顶窗口', color: colors.warning }, MM2: { name: '错配期·抄底信号', color: colors.orange },
    MM3: { name: '错配期·趋势转空', color: colors.warning }, MM4: { name: '错配期·趋势转多', color: colors.orange },
  }
  const mm = cd.mismatch ? mismatchTable[cd.mismatch] : null
  const age = Number.isInteger(cd.mismatch_age) && cd.mismatch_age >= 0 ? cd.mismatch_age : null
  const crossTime = age === 0 ? '最新一根日K' : age === null ? '计龄未知' : `${age} 根日K前`
  const cross = cd.mismatch === 'MM3' || cd.mismatch === 'MM4'
  const ageLabel = age === null ? '计龄未知' : cross ? `趋势已转向 ${age} 根日K` : `震荡${cd.mismatch === 'MM1' ? '已清仓' : '已持有'} ${age} 根日K`
  const scoreRows = [ ['trend', '趋势一致'], ['oscillation', '震荡确认'], ['resonance', '共振'], ['direction', '方向拐点'], ['volatility', '波动折损'] ] as const
  const scores = scoreRows.map(([key, label]) => {
    const n = cd.scores[key], value = Number.isFinite(n) ? n : null
    const color = value === null ? colors.gray : key === 'trend' ? value >= 25 ? colors.red : value > 0 ? colors.orange : colors.gray
      : key === 'oscillation' ? value >= 25 ? colors.green : value > 0 ? colors.orange : colors.gray
      : key === 'resonance' ? value >= 20 ? colors.green : value > 0 ? colors.orange : colors.gray
      : key === 'direction' ? value >= 15 ? colors.red : value > 5 ? colors.orange : colors.gray
      : value < 0 ? colors.green : colors.gray
    return { key, label, value, color }
  })
  const w = cd.trend_state?.week, d = cd.trend_state?.day
  const direction = w === 'down' && d === 'up' ? { text: '从周线开始下跌，当前为周线下跌中的反弹（背离），勿追涨。', color: colors.warning }
    : w === 'down' ? { text: '从周线开始下跌，大级别趋势向下；观察空仓等待反转。', color: colors.red }
    : w === 'up' && d === 'down' ? { text: '从日线开始回调，周线未转空；等待日线企稳与回补信号。', color: colors.orange }
    : w === 'up' && d === 'up' ? { text: cd.trend_state?.m60 === 'up' ? '日周小时趋势同向向上。' : cd.trend_state?.m60 === 'down' ? '日周趋势向上，小时回调；等待小时企稳。' : '日周趋势向上，小时依据不足。', color: colors.red }
    : { text: '日周趋势依据不足，等待已完成信号明确。', color: colors.gray }
  return { tier, scores, direction, volatility: decisionVolatility(cd),
    exposure: cd.reference_exposure_range || (cd.reference_exposure_cap === 0 ? '0%' : '—'),
    resonance: { name: r.name, color: r.color, dots: '●'.repeat(r.count) + '○'.repeat(5 - r.count), description: decisionResonanceReason(cd) },
    mismatch: mm ? { ...mm, ageLabel, detail: cross ? `趋势日线 ${crossTime}${cd.mismatch === 'MM3' ? '下穿' : '上穿'} MA10。${decisionMismatchReason(cd)}` : decisionMismatchReason(cd) } : null }
}

export function decisionContextIdentity(identity: { product: string; strategy: import('../types/newowProduct').NewowProductStrategy; frequency: import('../types/newowProduct').NewowProductFrequency }) {
  const background = ['5m', '15m', '30m'].includes(identity.frequency)
  return { background, identity: { product: identity.product, strategy: identity.strategy, frequency: background ? '60m' as const : identity.frequency, seriesKind: 'actual_dominant' as const } }
}
