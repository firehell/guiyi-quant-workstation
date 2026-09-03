import { ref } from 'vue'

import type { ProductAlertStateResponse } from '../api/alerts.ts'
import type { AlertRuntimeStatus } from '../utils/alertControl.ts'
import { ALERT_RULE_CODES, findAlertRuleByCode } from '../utils/alertRules.ts'
import type { MarketFrequency } from '../types/market.ts'

export interface HtdyAlertFactsIdentity { symbol: string; frequency: MarketFrequency }

export function useHtdyAlertFacts(dependencies: {
  fetchRuntime: () => Promise<AlertRuntimeStatus>
  fetchProductAlerts: (symbol: string) => Promise<ProductAlertStateResponse>
}) {
  const runtime = ref<'healthy' | 'degraded' | 'unavailable'>('unavailable')
  const ruleScope = ref('HTDY Rule / Scope 暂不可用')
  let generation = 0

  async function refresh(identity: HtdyAlertFactsIdentity) {
    const requestGeneration = ++generation
    const snapshot = { ...identity }
    const [runtimeResult, rulesResult] = await Promise.allSettled([
      dependencies.fetchRuntime(),
      dependencies.fetchProductAlerts(snapshot.symbol),
    ])
    if (requestGeneration !== generation) return
    runtime.value = runtimeResult.status === 'fulfilled'
      ? runtimeState(runtimeResult.value)
      : 'unavailable'
    ruleScope.value = rulesResult.status === 'fulfilled'
      ? ruleScopeText(rulesResult.value, snapshot)
      : 'HTDY Rule / Scope 暂不可用'
  }

  function dispose() { generation += 1 }
  return { runtime, ruleScope, refresh, dispose }
}

function runtimeState(status: AlertRuntimeStatus): 'healthy' | 'degraded' | 'unavailable' {
  return status === 'ok' || status === 'healthy' ? 'healthy' : status === 'disabled' ? 'unavailable' : 'degraded'
}

function ruleScopeText(response: ProductAlertStateResponse, identity: HtdyAlertFactsIdentity): string {
  const rule = findAlertRuleByCode(response.rules, ALERT_RULE_CODES.HTDY)
  return rule
    ? `${rule.display_name} (${ALERT_RULE_CODES.HTDY}) · ${identity.symbol.toUpperCase()} ${identity.frequency} · ${rule.enabled_frequencies.includes(identity.frequency) ? '当前 Scope 已启用' : '当前 Scope 未启用'} · 仅只读展示`
    : 'HTDY Rule / Scope 暂不可用'
}
