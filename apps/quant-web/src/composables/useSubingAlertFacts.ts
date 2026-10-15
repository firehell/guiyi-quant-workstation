import type { ProductAlertStateResponse } from '../api/alerts.ts'
import type { RuntimeHealthResponse } from '../api/runtime.ts'
import { normalizeRuntimeAlertProjection } from '../utils/runtimeHealthTypes.ts'
import { ALERT_RULE_CODES } from '../utils/alertRules.ts'
import { SUBING_FREQUENCIES, type MarketFrequency } from '../types/market.ts'
import { validatedAlertScope, type AlertFactsIdentity } from '../utils/alertScopeFacts.ts'
import { useIdentityBoundResource } from './useIdentityBoundResource.ts'

export type SubingAlertFactsIdentity = AlertFactsIdentity
export interface SubingRuleScopeFact {
  ruleCode: typeof ALERT_RULE_CODES.SUBING_THS
  displayName: string
  symbol: string
  frequency: MarketFrequency
  enabled: boolean
  enabledFrequencies: readonly MarketFrequency[]
}

export function useSubingAlertFacts(dependencies: {
  fetchRuntime: () => Promise<RuntimeHealthResponse>
  fetchProductAlerts: (symbol: string) => Promise<ProductAlertStateResponse>
}) {
  const runtimeResource = useIdentityBoundResource({
    key: () => 'runtime',
    load: dependencies.fetchRuntime,
    project: (response: RuntimeHealthResponse) => normalizeRuntimeAlertProjection(response.components.alert),
  })
  const ruleResource = useIdentityBoundResource({
    key: (identity: SubingAlertFactsIdentity) => `${identity.symbol}:${identity.frequency}`,
    load: (identity: SubingAlertFactsIdentity) => dependencies.fetchProductAlerts(identity.symbol),
    project: ruleScopeFact,
  })
  async function refresh(identity: SubingAlertFactsIdentity) {
    const snapshot = { symbol: identity.symbol.toLowerCase(), frequency: identity.frequency }
    await Promise.all([runtimeResource.refresh(snapshot), ruleResource.refresh(snapshot)])
  }
  function dispose() { runtimeResource.dispose(); ruleResource.dispose() }
  return {
    rule: ruleResource.value, ruleUnavailable: ruleResource.unavailable,
    runtime: runtimeResource.value, runtimeUnavailable: runtimeResource.unavailable,
    refresh, dispose,
  }
}

function ruleScopeFact(response: ProductAlertStateResponse, identity: SubingAlertFactsIdentity): SubingRuleScopeFact {
  const rule = validatedAlertScope(response, identity, {
    ruleCode: ALERT_RULE_CODES.SUBING_THS, displayName: '苏冰预警', frequencies: SUBING_FREQUENCIES,
  })
  return {
    ruleCode: ALERT_RULE_CODES.SUBING_THS,
    displayName: rule.display_name,
    symbol: identity.symbol,
    frequency: identity.frequency,
    enabled: rule.enabled_frequencies.includes(identity.frequency),
    enabledFrequencies: [...rule.enabled_frequencies],
  }
}
