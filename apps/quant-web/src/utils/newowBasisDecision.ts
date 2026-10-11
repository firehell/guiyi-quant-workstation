import type { Cdv2, NewowDecisionV2 } from '../types/newowDecisionV2'

export type DecisionBasis = 'week' | 'day'
export type BasisRawState = 'holding' | 'cleared' | 'idle'
export type BasisDecisionRow = 'DD' | 'DU' | 'DN' | 'UD' | 'UN' | 'UU' | 'N'
export type BasisStrength = 'violate' | 'tip' | 'ok'
type Fact = Cdv2['facts'][number]
export const NEWOW_BASIS_DECISION_VERSION = 'newow_basis_decision_v3379_v1'
export interface BasisStance {
  label: string
  color: string
  risk: 'bullish' | 'cautious' | 'warning' | 'bearish'
}
export interface BasisDecision {
  version: typeof NEWOW_BASIS_DECISION_VERSION
  row: BasisDecisionRow
  action: string
  strength: BasisStrength
  conflict: boolean
  reason: string
  basis: DecisionBasis
  basisName: string
  dirFull: string
  execFull: string
  strengthName: string
  strengthText: string
  stance: BasisStance
  directionFact: Fact
  executionFact: Fact
}
const reasons: Record<BasisDecisionRow, string> = {
  DD: '大级别空头确立，反弹不改趋势', DU: '主周期偏空，反弹不追高', DN: '主周期偏空，暂不建仓',
  UD: '主周期看多，短线回调待企稳', UN: '主周期看多，等待买点', UU: '各周期方向一致，趋势成立',
  N: '主周期未表态，等待',
}
const stances: Record<BasisDecisionRow, BasisStance> = {
  DD: { label: '空仓防御', color: '#34c759', risk: 'bearish' },
  DU: { label: '谨慎观望', color: '#ff6b35', risk: 'warning' },
  DN: { label: '空仓防御', color: '#34c759', risk: 'bearish' },
  UD: { label: '谨慎持仓', color: '#ff9500', risk: 'cautious' },
  UN: { label: '谨慎持仓', color: '#ff9500', risk: 'cautious' },
  UU: { label: '积极做多', color: '#ff3b30', risk: 'bullish' },
  N: { label: '谨慎持仓', color: '#8e8e93', risk: 'cautious' },
}
// Public v3.3.79 rendering judge, independent of CDV2 scoring and strategy decisions.
export function cdtDecide(D: BasisRawState, X: BasisRawState): Pick<BasisDecision, 'row' | 'action' | 'strength' | 'conflict'> {
  if (D === 'idle') return { row: 'N', action: '等待', strength: 'tip', conflict: false }
  if (D === 'cleared' && X === 'cleared') return { row: 'DD', action: '空仓', strength: 'violate', conflict: false }
  if (D === 'cleared' && X === 'holding') return { row: 'DU', action: '减仓', strength: 'tip', conflict: false }
  if (D === 'cleared') return { row: 'DN', action: '空仓', strength: 'tip', conflict: false }
  if (X === 'cleared') return { row: 'UD', action: '等待', strength: 'tip', conflict: true }
  if (X === 'idle') return { row: 'UN', action: '等待', strength: 'tip', conflict: false }
  return { row: 'UU', action: '建仓', strength: 'ok', conflict: false }
}
function rawState(fact: Fact): BasisRawState | null {
  return fact.state === 'buy' || fact.state === 'hold' ? 'holding'
    : fact.state === 'sell' ? 'cleared' : fact.state === 'wait' ? 'idle' : null
}
function validFact(fact: Fact, frequency: string, asOf: number): boolean {
  return fact.status === 'ready' && fact.frequency === frequency &&
    typeof fact.physical_contract === 'string' && fact.physical_contract.trim().length > 0 &&
    typeof fact.segment_id === 'string' && fact.segment_id.trim().length > 0 &&
    typeof fact.bar_end === 'string' && Number.isFinite(Date.parse(fact.bar_end)) &&
    Date.parse(fact.bar_end) <= asOf
}
function triggerText(row: BasisDecisionRow, dir: string, exec: string): string {
  switch (row) {
    case 'DD': return dir + '与' + exec + '同时清仓'
    case 'DU': return dir + '清仓、' + exec + '建仓'
    case 'DN': return dir + '清仓、' + exec + '未表态'
    case 'UD': return dir + '建仓、' + exec + '清仓'
    case 'UN': return dir + '建仓、' + exec + '未表态'
    case 'UU': return dir + '与' + exec + '同时建仓'
    default: return dir + '未表态'
  }
}
export function deriveBasisDecision(
  value: NewowDecisionV2 | null,
  strategy: string,
  basis: DecisionBasis = 'week',
  dominant: 'trend' | 'oscillation' | null = null,
): BasisDecision | null {
  const family = strategy === 'dual' ? dominant === 'oscillation' ? 'oscillation' : 'trend'
    : strategy === 'trend' || strategy === 'oscillation' ? strategy : null
  if (!family || !value?.cdv2 || (basis !== 'week' && basis !== 'day')) return null
  const cd = value.cdv2, asOf = Date.parse(cd.as_of)
  if (!Number.isFinite(asOf) || !Array.isArray(cd.facts)) return null
  const roles = basis === 'day' ? ['day', 'm60'] : ['week', 'day']
  const frequencies = basis === 'day' ? ['1d', '60m'] : ['1w', '1d']
  const direction = cd.facts.filter(f => f.role === family + '_' + roles[0])
  const execution = cd.facts.filter(f => f.role === family + '_' + roles[1])
  if (direction.length !== 1 || execution.length !== 1) return null
  const directionFact = direction[0]!, executionFact = execution[0]!
  if (!validFact(directionFact, frequencies[0]!, asOf) || !validFact(executionFact, frequencies[1]!, asOf) ||
      directionFact.physical_contract !== executionFact.physical_contract ||
      directionFact.segment_id !== executionFact.segment_id) return null
  const D = rawState(directionFact), X = rawState(executionFact)
  // Missing facts must not inherit the source page's fallback-to-idle behavior.
  if (D === null || X === null) return null
  const decision = cdtDecide(D, X), dirFull = basis === 'week' ? '周线' : '日线', execFull = basis === 'week' ? '日线' : '60分'
  return {
    version: NEWOW_BASIS_DECISION_VERSION, ...decision, reason: reasons[decision.row], basis,
    basisName: basis === 'week' ? '周线定方向，日线定买卖点' : '日线定方向，60分定买卖点',
    dirFull, execFull, strengthName: { violate: '违反', tip: '提示', ok: '遵守' }[decision.strength],
    strengthText: triggerText(decision.row, dirFull, execFull), stance: { ...stances[decision.row] },
    directionFact, executionFact,
  }
}
