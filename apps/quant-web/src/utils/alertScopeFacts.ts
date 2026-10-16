import type { ProductAlertRuleState, ProductAlertStateResponse } from '../api/alerts.ts'
import type { MarketFrequency } from '../types/market.ts'
import { matchesAlertRuleCode } from './alertRules.ts'

export interface AlertFactsIdentity { symbol: string; frequency: MarketFrequency }

/** Shared Scope relationships; callers supply their registered rule policy. */
export function validatedAlertScope(
  response: ProductAlertStateResponse,
  identity: AlertFactsIdentity,
  policy: { ruleCode: string; displayName: string; frequencies: readonly MarketFrequency[] },
): ProductAlertRuleState {
  if (typeof response.symbol !== 'string' || response.symbol.toLowerCase() !== identity.symbol
    || !policy.frequencies.includes(identity.frequency) || !Array.isArray(response.rules)) {
    throw new Error('product identity mismatch')
  }
  const matches = response.rules.filter(rule => rule && matchesAlertRuleCode(rule, policy.ruleCode))
  const rule = matches[0]
  if (matches.length !== 1 || !rule || rule.display_name !== policy.displayName
    || rule.kind !== 'indicator_observation' || !Array.isArray(rule.input_frequencies)
    || !rule.input_frequencies.length || !Array.isArray(rule.enabled_frequencies)
    || rule.input_frequencies.some(frequency => !policy.frequencies.includes(frequency))
    || rule.enabled_frequencies.some(frequency => !rule.input_frequencies.includes(frequency))
    || new Set(rule.input_frequencies).size !== rule.input_frequencies.length
    || new Set(rule.enabled_frequencies).size !== rule.enabled_frequencies.length
    || rule.enabled_for_product !== (rule.enabled_frequencies.length > 0)) {
    throw new Error('rule scope mismatch')
  }
  return rule
}
