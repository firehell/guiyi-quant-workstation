import { ref } from 'vue'
import type { ProductAlertStateResponse, ProductAlertRuleState } from '../api/alerts.ts'
import type { RuntimeHealthResponse } from '../api/runtime.ts'
import { normalizeRuntimeAlertProjection, type RuntimeAlertProjection } from '../utils/runtimeHealthTypes.ts'
import { ALERT_RULE_CODES, findAlertRuleByCode } from '../utils/alertRules.ts'
import type { MarketFrequency } from '../types/market.ts'

export interface SubingAlertFactsIdentity { symbol: string; frequency: MarketFrequency }

export function useSubingAlertFacts(dependencies: {
  fetchRuntime: () => Promise<RuntimeHealthResponse>
  fetchProductAlerts: (symbol: string) => Promise<ProductAlertStateResponse>
}) {
  const rule = ref<string | null>(null)
  const ruleUnavailable = ref(false)
  const runtime = ref<RuntimeAlertProjection | null>(null)
  const runtimeUnavailable = ref(false)
  let generation = 0
  let activeIdentityKey: string | null = null

  async function refresh(identity: SubingAlertFactsIdentity) {
    const requestGeneration = ++generation
    const snapshot = { symbol: identity.symbol.toLowerCase(), frequency: identity.frequency }
    const nextIdentityKey = `${snapshot.symbol}:${snapshot.frequency}`
    if (activeIdentityKey !== nextIdentityKey) {
      activeIdentityKey = nextIdentityKey
      rule.value = null
      ruleUnavailable.value = true
    }
    const [runtimeResult, rulesResult] = await Promise.allSettled([
      dependencies.fetchRuntime(), dependencies.fetchProductAlerts(snapshot.symbol),
    ])
    if (requestGeneration !== generation) return
    if (runtimeResult.status === 'fulfilled') {
      try {
        runtime.value = normalizeRuntimeAlertProjection(runtimeResult.value.components.alert)
        runtimeUnavailable.value = false
      } catch { runtime.value = null; runtimeUnavailable.value = true }
    } else { runtime.value = null; runtimeUnavailable.value = true }
    if (rulesResult.status === 'fulfilled') {
      try { rule.value = ruleScopeText(rulesResult.value, snapshot); ruleUnavailable.value = false }
      catch { rule.value = null; ruleUnavailable.value = true }
    } else { rule.value = null; ruleUnavailable.value = true }
  }

  function dispose() { generation += 1; activeIdentityKey = null }
  return { rule, ruleUnavailable, runtime, runtimeUnavailable, refresh, dispose }
}

function ruleScopeText(response: ProductAlertStateResponse, identity: SubingAlertFactsIdentity): string {
  if (response.symbol.toLowerCase() !== identity.symbol || identity.frequency !== '15m') throw new Error('product identity mismatch')
  const current = findAlertRuleByCode(response.rules, ALERT_RULE_CODES.SUBING_THS)
  if (!current || !isSubingRule(current)) throw new Error('subing rule mismatch')
  if (current.enabled_frequencies.some((frequency) => frequency !== '15m') || (current.enabled_for_product !== current.enabled_frequencies.includes('15m'))) throw new Error('subing scope mismatch')
  const enabledFrequencies = current.enabled_frequencies.length ? current.enabled_frequencies.join(', ') : '无'
  return `Rule ${current.display_name} (${ALERT_RULE_CODES.SUBING_THS}) · 状态不可判定 · 当前 Scope ${current.enabled_for_product ? '已启用' : '未启用'} · enabled_frequencies=${enabledFrequencies} · ${identity.symbol.toUpperCase()} 15m · 仅只读展示`
}

function isSubingRule(rule: ProductAlertRuleState): boolean {
  return rule.display_name === '苏冰预警'
    && rule.kind === 'indicator_observation'
    && rule.input_frequencies.length === 1
    && rule.input_frequencies[0] === '15m'
}
