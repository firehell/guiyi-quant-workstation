import {
  MARKET_FREQUENCIES,
  type AlertEvent,
  type HtdyAlertEvent,
  type MarketFrequency,
  type SubingStrategyAlertEvent,
} from '../types/market.ts'

export const HTDY_ALERT_RULE_CODE = 'htdy_original_15m'
export const SUBING_STRATEGY_RULE_CODE = 'subing_strategy_v1'

export const ALERT_RULE_CODES = {
  HTDY: HTDY_ALERT_RULE_CODE,
  SUBING: SUBING_STRATEGY_RULE_CODE,
} as const

export type AlertRuleCode = typeof ALERT_RULE_CODES[keyof typeof ALERT_RULE_CODES]
export type AlertDirection = 'buy' | 'sell'

interface AlertRuleIdentity {
  readonly rule_code: string
}

export interface AlertRulePresentation {
  ruleCode: AlertRuleCode
  shortLabel: string
  resultNoun: '观察' | '策略动作'
  markerTone: 'htdy' | null
  persistentFrequencies: readonly MarketFrequency[]
}

export const ALERT_RULE_PRESENTATIONS: readonly AlertRulePresentation[] = [
  {
    ruleCode: ALERT_RULE_CODES.HTDY,
    shortLabel: '火天大有',
    resultNoun: '观察',
    markerTone: 'htdy',
    persistentFrequencies: MARKET_FREQUENCIES,
  },
  {
    ruleCode: ALERT_RULE_CODES.SUBING,
    shortLabel: '苏冰',
    resultNoun: '策略动作',
    markerTone: null,
    persistentFrequencies: ['15m'],
  },
]

const PRESENTATION_BY_CODE = new Map(
  ALERT_RULE_PRESENTATIONS.map((presentation) => [presentation.ruleCode, presentation]),
)

export function getAlertRulePresentation(ruleCode: string): AlertRulePresentation | null {
  return PRESENTATION_BY_CODE.get(ruleCode as AlertRuleCode) ?? null
}

export function matchesAlertRuleCode(
  event: AlertRuleIdentity,
  ruleCode: string,
): boolean {
  return event.rule_code === ruleCode
}

export function findAlertRuleByCode<T extends AlertRuleIdentity>(
  rules: readonly T[],
  ruleCode: string,
): T | undefined {
  return rules.find((rule) => matchesAlertRuleCode(rule, ruleCode))
}

export function findAlertRuleForEvent<T extends AlertRuleIdentity>(
  rules: readonly T[],
  event: AlertRuleIdentity,
): T | undefined {
  return rules.find((rule) => rule.rule_code === event.rule_code)
}

export function isHtdyAlertEvent(event: AlertEvent): event is HtdyAlertEvent {
  return matchesAlertRuleCode(event, ALERT_RULE_CODES.HTDY)
}

export function isSubingStrategyAlertEvent(
  event: AlertEvent,
): event is SubingStrategyAlertEvent {
  return matchesAlertRuleCode(event, ALERT_RULE_CODES.SUBING)
}

export function alertRuleShortLabel(ruleCode: string): string {
  return getAlertRulePresentation(ruleCode)?.shortLabel ?? '未知提醒'
}

export function alertEventRuleShortLabel(event: AlertRuleIdentity): string {
  return alertRuleShortLabel(event.rule_code)
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

export function alertEventResultLabel(
  event: AlertRuleIdentity,
  directions: readonly AlertDirection[],
): string {
  return alertResultLabel(event.rule_code, directions)
}

export function strategyActionLabel(kind: string): string {
  if (kind === 'open_long') return '建多'
  if (kind === 'open_short') return '建空'
  if (kind === 'close_long') return '清多'
  if (kind === 'close_short') return '清空'
  return '策略动作'
}

export function alertDirectionalTone(
  ruleCode: string,
  directions: readonly AlertDirection[],
): AlertDirection | null {
  if (!getAlertRulePresentation(ruleCode) || directions.length !== 1) return null
  return directions[0] === 'buy' || directions[0] === 'sell' ? directions[0] : null
}

export function alertEventDirectionalTone(
  event: AlertRuleIdentity,
  directions: readonly AlertDirection[],
): AlertDirection | null {
  return alertDirectionalTone(event.rule_code, directions)
}

export function alertEventMarkerTone(
  event: AlertRuleIdentity,
): AlertRulePresentation['markerTone'] {
  return getAlertRulePresentation(event.rule_code)?.markerTone ?? null
}

export function alertEventIdentityKey(event: AlertEvent): string {
  return event.action_id
    ?? `${event.rule_code}:${event.symbol}:${event.frequency}:${event.bar_end}`
}
