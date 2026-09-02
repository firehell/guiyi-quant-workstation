import {
  MARKET_FREQUENCIES,
  type AlertEvent,
  type AlertDirection,
  type AlertRuleCode,
  type HtdyAlertEvent,
  type MarketFrequency,
  type SubingThsAlertEvent,
} from '../types/market.ts'

export const HTDY_ALERT_RULE_CODE = 'htdy_original_15m'
export const SUBING_THS_ALERT_RULE_CODE = 'subing_ths_alert_15m_v1'
export const ALERT_RULE_CODES = {
  HTDY: HTDY_ALERT_RULE_CODE,
  SUBING_THS: SUBING_THS_ALERT_RULE_CODE,
} as const

export type { AlertRuleCode } from '../types/market.ts'

interface AlertRuleIdentity { readonly rule_code: string }

export interface AlertRulePresentation {
  ruleCode: AlertRuleCode
  shortLabel: string
  resultNoun: '观察' | '预警'
  markerTone: 'htdy' | 'directional'
  persistentFrequencies: readonly MarketFrequency[]
}

export const ALERT_RULE_PRESENTATIONS: readonly AlertRulePresentation[] = [{
  ruleCode: ALERT_RULE_CODES.HTDY,
  shortLabel: '火天大有',
  resultNoun: '观察',
  markerTone: 'htdy',
  persistentFrequencies: MARKET_FREQUENCIES,
}, {
  ruleCode: ALERT_RULE_CODES.SUBING_THS,
  shortLabel: '苏冰预警',
  resultNoun: '预警',
  markerTone: 'directional',
  persistentFrequencies: ['15m'],
}]

export function getAlertRulePresentation(ruleCode: string): AlertRulePresentation | null {
  return ALERT_RULE_PRESENTATIONS.find((presentation) => presentation.ruleCode === ruleCode) ?? null
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

export function isSubingThsAlertEvent(event: AlertEvent): event is SubingThsAlertEvent {
  return matchesAlertRuleCode(event, ALERT_RULE_CODES.SUBING_THS)
}

export function alertRuleShortLabel(ruleCode: string): string {
  return getAlertRulePresentation(ruleCode)?.shortLabel ?? '未知提醒'
}

export function alertEventRuleShortLabel(event: AlertRuleIdentity): string {
  return alertRuleShortLabel(event.rule_code)
}

export function alertResultLabel(ruleCode: string, directions: readonly AlertDirection[]): string {
  if (ruleCode === ALERT_RULE_CODES.SUBING_THS) {
    return directions.length === 1 && directions[0] === 'buy'
      ? '多头预警'
      : directions.length === 1 && directions[0] === 'sell'
        ? '空头预警'
        : '提醒记录'
  }
  if (ruleCode !== ALERT_RULE_CODES.HTDY) return '提醒记录'
  const values = new Set(directions)
  if (values.has('buy') && values.has('sell')) return '买入/卖出观察'
  if (values.has('buy')) return '买入观察'
  if (values.has('sell')) return '卖出观察'
  return '提醒记录'
}

export function alertEventHomeResultLabel(event: AlertEvent): string {
  if (isSubingThsAlertEvent(event)) return alertResultLabel(event.rule_code, event.result_codes)
  const values = new Set(event.result_codes)
  if (values.has('buy') && values.has('sell')) return '双向观察'
  if (values.has('buy')) return '买观察'
  if (values.has('sell')) return '卖观察'
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

export function alertEventMarkerTone(event: AlertRuleIdentity): 'htdy' | 'directional' | null {
  return getAlertRulePresentation(event.rule_code)?.markerTone ?? null
}

export function normalizeAlertEventFacts(
  ruleCode: unknown,
  frequency: MarketFrequency,
  values: readonly unknown[],
): { ruleCode: AlertRuleCode; resultCodes: AlertEvent['result_codes'] } {
  const directions = values.filter((value): value is AlertDirection => value === 'buy' || value === 'sell')
  if (directions.length !== values.length || !directions.length || new Set(directions).size !== directions.length) {
    throw new Error('result_codes are invalid')
  }
  if (ruleCode === ALERT_RULE_CODES.HTDY) {
    return { ruleCode, resultCodes: directions }
  }
  if (ruleCode === ALERT_RULE_CODES.SUBING_THS && frequency === '15m' && directions.length === 1) {
    return { ruleCode, resultCodes: directions as ['buy'] | ['sell'] }
  }
  throw new Error('rule_code is invalid')
}

export function alertEventIdentityKey(event: AlertEvent): string {
  return `${event.rule_code}:${event.symbol}:${event.frequency}:${event.bar_end}`
}

export function alertEventRuleCode(event: AlertEvent): AlertRuleCode {
  return event.rule_code
}
