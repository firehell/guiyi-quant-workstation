import { computed } from 'vue'
import type { ProductAlertStateResponse } from '../api/alerts.ts'
import type { AlertRuntimeStatus } from '../utils/alertControl.ts'
import { ALERT_RULE_CODES } from '../utils/alertRules.ts'
import { MARKET_FREQUENCIES } from '../types/market.ts'
import { validatedAlertScope, type AlertFactsIdentity } from '../utils/alertScopeFacts.ts'
import { useIdentityBoundResource } from './useIdentityBoundResource.ts'

export type HtdyAlertFactsIdentity = AlertFactsIdentity

export function useHtdyAlertFacts(dependencies: {
  fetchRuntime: (signal?: AbortSignal) => Promise<AlertRuntimeStatus>
  fetchProductAlerts: (symbol: string, signal?: AbortSignal) => Promise<ProductAlertStateResponse>
}) {
  const runtimeResource = useIdentityBoundResource({
    key: () => 'runtime',
    load: (_identity: HtdyAlertFactsIdentity, signal) => dependencies.fetchRuntime(signal),
    project: runtimeState,
  })
  const scopeResource = useIdentityBoundResource({
    key: (identity: HtdyAlertFactsIdentity) => `${identity.symbol}:${identity.frequency}`,
    load: (identity: HtdyAlertFactsIdentity, signal) => dependencies.fetchProductAlerts(identity.symbol, signal),
    project: ruleScopeText,
  })

  async function refresh(identity: HtdyAlertFactsIdentity) {
    const snapshot = { symbol: identity.symbol.toLowerCase(), frequency: identity.frequency }
    await Promise.all([runtimeResource.refresh(snapshot), scopeResource.refresh(snapshot)])
  }
  function dispose() { runtimeResource.dispose(); scopeResource.dispose() }
  const runtime = computed(() => runtimeResource.value.value ?? 'unavailable')
  const ruleScope = computed(() => scopeResource.value.value ?? 'HTDY Rule / Scope 暂不可用')
  return { runtime, ruleScope, refresh, dispose }
}

function runtimeState(status: AlertRuntimeStatus): 'healthy' | 'degraded' | 'unavailable' {
  return status === 'ok' || status === 'healthy' ? 'healthy' : status === 'disabled' ? 'unavailable' : 'degraded'
}

function ruleScopeText(response: ProductAlertStateResponse, identity: HtdyAlertFactsIdentity): string {
  const rule = validatedAlertScope(response, identity, {
    ruleCode: ALERT_RULE_CODES.HTDY, displayName: '火天大有', frequencies: MARKET_FREQUENCIES,
  })
  return `${rule.display_name} (${ALERT_RULE_CODES.HTDY}) · ${identity.symbol.toUpperCase()} ${identity.frequency} · ${rule.enabled_frequencies.includes(identity.frequency) ? '当前 Scope 已启用' : '当前 Scope 未启用'} · 仅只读展示`
}
