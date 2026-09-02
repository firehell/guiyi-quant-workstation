import {
  MARKET_FREQUENCIES,
  type AlertEvent,
  type HtdyAlertEvent,
  type MarketFrequency,
} from '../types/market.ts'

export const HTDY_ALERT_RULE_CODE = 'htdy_original_15m'
export const ALERT_RULE_CODES = { HTDY: HTDY_ALERT_RULE_CODE } as const

export type AlertRuleCode = typeof HTDY_ALERT_RULE_CODE
export type AlertDirection = 'buy' | 'sell'

interface AlertRuleIdentity { readonly rule_code: string }

export interface AlertRulePresentation {
  ruleCode: AlertRuleCode
  shortLabel: string
  resultNoun: '观察'
  markerTone: 'htdy'
  persistentFrequencies: readonly MarketFrequency[]
}

export const ALERT_RULE_PRESENTATIONS: readonly AlertRulePresentation[] = [{
  ruleCode: ALERT_RULE_CODES.HTDY,
  shortLabel: '火天大有',
  resultNoun: '观察',
  markerTone: 'htdy',
  persistentFrequencies: MARKET_FREQUENCIES,
}]

export function getAlertRulePresentation(ruleCode: string): AlertRulePresentation | null {
  return ruleCode === ALERT_RULE_CODES.HTDY ? ALERT_RULE_PRESENTATIONS[0]! : null
}

export function matchesAlertRuleCode(event: AlertRuleIdentity, ruleCode: string): boolean {
  return event.rule_code === ruleCode
}

export function findAlertRuleByCode<T extends AlertRuleIdentity>(rules: readonly T[], ruleCode: string): T | undefined {
  return rules.find((rule) => matchesAlertRuleCode(rule, ruleCode))
}

export function findAlertRuleForEvent<T extends AlertRuleIdentity>(rules: readonly T[], event: AlertRuleIdentity): T | undefined {
  return rules.find((rule) => rule.rule_code === event.rule_code)
}

export function isHtdyAlertEvent(event: AlertEvent): event is HtdyAlertEvent {
  return matchesAlertRuleCode(event, ALERT_RULE_CODES.HTDY)
}

export function alertRuleShortLabel(ruleCode: string): string {
  return getAlertRulePresentation(ruleCode)?.shortLabel ?? '未知提醒'
}

export function alertEventRuleShortLabel(event: AlertRuleIdentity): string {
  return alertRuleShortLabel(event.rule_code)
}

export function alertResultLabel(ruleCode: string, directions: readonly AlertDirection[]): string {
  if (!getAlertRulePresentation(ruleCode)) return '提醒记录'
  const values = new Set(directions)
  if (values.has('buy') && values.has('sell')) return '买入/卖出观察'
  if (values.has('buy')) return '买入观察'
  if (values.has('sell')) return '卖出观察'
  return '提醒记录'
}

export function alertEventResultLabel(event: AlertRuleIdentity, directions: readonly AlertDirection[]): string {
  return alertResultLabel(event.rule_code, directions)
}

export function alertDirectionalTone(ruleCode: string, directions: readonly AlertDirection[]): AlertDirection | null {
  if (!getAlertRulePresentation(ruleCode) || directions.length !== 1) return null
  return directions[0] === 'buy' || directions[0] === 'sell' ? directions[0] : null
}

export function alertEventDirectionalTone(event: AlertRuleIdentity, directions: readonly AlertDirection[]): AlertDirection | null {
  return alertDirectionalTone(event.rule_code, directions)
}

export function alertEventMarkerTone(event: AlertRuleIdentity): 'htdy' | null {
  return getAlertRulePresentation(event.rule_code)?.markerTone ?? null
}

export function alertEventIdentityKey(event: AlertEvent): string {
  return `${event.rule_code}:${event.symbol}:${event.frequency}:${event.bar_end}`
}
