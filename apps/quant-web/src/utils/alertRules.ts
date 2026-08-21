import type { MarketFrequency } from '../types/market.ts'

export const ALERT_RULE_CODES = {
  HTDY: 'htdy_original_15m',
  SUBING: 'subing_entry_signal_v1',
} as const

export type AlertRuleCode = typeof ALERT_RULE_CODES[keyof typeof ALERT_RULE_CODES]
export type AlertDirection = 'buy' | 'sell'

export interface AlertRulePresentation {
  ruleCode: AlertRuleCode
  shortLabel: string
  resultNoun: '观察' | '信号'
  markerTone: 'htdy' | null
  persistentFrequencies: readonly MarketFrequency[]
}

export const ALERT_RULE_PRESENTATIONS: readonly AlertRulePresentation[] = [
  {
    ruleCode: ALERT_RULE_CODES.HTDY,
    shortLabel: '火天大有',
    resultNoun: '观察',
    markerTone: 'htdy',
    persistentFrequencies: ['15m'],
  },
  {
    ruleCode: ALERT_RULE_CODES.SUBING,
    shortLabel: '苏冰',
    resultNoun: '信号',
    markerTone: null,
    persistentFrequencies: ['5m', '15m'],
  },
]

const PRESENTATION_BY_CODE = new Map(
  ALERT_RULE_PRESENTATIONS.map((presentation) => [presentation.ruleCode, presentation]),
)

export function getAlertRulePresentation(ruleCode: string): AlertRulePresentation | null {
  return PRESENTATION_BY_CODE.get(ruleCode as AlertRuleCode) ?? null
}

export function alertRuleShortLabel(ruleCode: string): string {
  return getAlertRulePresentation(ruleCode)?.shortLabel ?? '未知提醒'
}

export function alertResultLabel(ruleCode: string, directions: readonly AlertDirection[]): string {
  const presentation = getAlertRulePresentation(ruleCode)
  if (!presentation) return '提醒记录'
  const values = new Set(directions)
  if (values.has('buy') && values.has('sell')) return `买入/卖出${presentation.resultNoun}`
  if (values.has('buy')) return `买入${presentation.resultNoun}`
  if (values.has('sell')) return `卖出${presentation.resultNoun}`
  return '提醒记录'
}

export function alertDirectionalTone(
  ruleCode: string,
  directions: readonly AlertDirection[],
): AlertDirection | null {
  if (!getAlertRulePresentation(ruleCode) || directions.length !== 1) return null
  return directions[0] === 'buy' || directions[0] === 'sell' ? directions[0] : null
}
