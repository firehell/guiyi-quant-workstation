import { computed, ref, type Ref } from 'vue'
import type {
  AlertRuntimeStatus,
  ProductAlertRuleState,
  ProductAlertStateResponse,
} from '../api/alerts.ts'
import { isCurrentAlertMutation } from '../utils/alertControl.ts'


interface Dependencies {
  symbol: Ref<string>
  fetchProductAlerts: (symbol: string) => Promise<ProductAlertStateResponse>
  fetchRuntimeStatus: () => Promise<AlertRuntimeStatus>
  setProductEnabled: (
    ruleCode: string,
    symbol: string,
    enabled: boolean,
  ) => Promise<ProductAlertRuleState>
  notifyError: (message: string) => void
}

export function useProductAlertScope(dependencies: Dependencies) {
  const alertRules = ref<ProductAlertRuleState[]>([])
  const alertRuntimeStatus = ref<AlertRuntimeStatus | null>(null)
  const alertLoading = ref(false)
  const savingRuleCodes = ref<Set<string>>(new Set())
  const rulesByCode = computed(() => new Map(
    alertRules.value.map((rule) => [rule.rule_code, rule]),
  ))
  const htdyRule = computed(() => rulesByCode.value.get('htdy_original_15m') ?? null)
  const subingRule = computed(() => rulesByCode.value.get('subing_entry_signal_v1') ?? null)
  let generation = 0

  async function refresh(): Promise<void> {
    const requestedSymbol = dependencies.symbol.value
    if (!requestedSymbol) return
    const requestGeneration = ++generation
    alertLoading.value = true
    alertRules.value = []
    try {
      const [scope, runtimeStatus] = await Promise.all([
        dependencies.fetchProductAlerts(requestedSymbol),
        dependencies.fetchRuntimeStatus(),
      ])
      if (!isCurrent(requestGeneration, requestedSymbol)) return
      alertRules.value = scope.rules
      alertRuntimeStatus.value = runtimeStatus
    } catch {
      if (!isCurrent(requestGeneration, requestedSymbol)) return
      alertRules.value = []
      alertRuntimeStatus.value = 'failed'
    } finally {
      if (requestGeneration === generation) alertLoading.value = false
    }
  }

  async function toggle(ruleCode: string, enabled: boolean): Promise<void> {
    const current = rulesByCode.value.get(ruleCode)
    const requestedSymbol = dependencies.symbol.value
    const requestGeneration = generation
    if (!current || !requestedSymbol || savingRuleCodes.value.has(ruleCode)) return
    savingRuleCodes.value = new Set(savingRuleCodes.value).add(ruleCode)
    try {
      const updated = await dependencies.setProductEnabled(
        ruleCode,
        requestedSymbol,
        enabled,
      )
      if (isCurrentAlertMutation({
        requestGeneration,
        currentGeneration: generation,
        requestedSymbol,
        currentSymbol: dependencies.symbol.value,
        requestedRuleCode: ruleCode,
        currentRuleCode: rulesByCode.value.get(ruleCode)?.rule_code,
        updatedRuleCode: updated.rule_code,
      })) {
        alertRules.value = alertRules.value.map((rule) => (
          rule.rule_code === ruleCode ? updated : rule
        ))
      }
    } catch {
      dependencies.notifyError('Alert Scope 更新失败')
    } finally {
      const saving = new Set(savingRuleCodes.value)
      saving.delete(ruleCode)
      savingRuleCodes.value = saving
    }
  }

  function isCurrent(requestGeneration: number, requestedSymbol: string): boolean {
    return requestGeneration === generation
      && dependencies.symbol.value === requestedSymbol
  }

  function dispose(): void {
    generation += 1
    alertLoading.value = false
    savingRuleCodes.value = new Set()
  }

  return {
    alertRules,
    htdyRule,
    subingRule,
    alertRuntimeStatus,
    alertLoading,
    savingRuleCodes,
    refresh,
    toggle,
    dispose,
  }
}
