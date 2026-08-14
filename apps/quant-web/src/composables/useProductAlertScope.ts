import { ref, type Ref } from 'vue'
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
  const alertRule = ref<ProductAlertRuleState | null>(null)
  const alertRuntimeStatus = ref<AlertRuntimeStatus | null>(null)
  const alertLoading = ref(false)
  const alertSaving = ref(false)
  let generation = 0

  async function refresh(): Promise<void> {
    const requestedSymbol = dependencies.symbol.value
    if (!requestedSymbol) return
    const requestGeneration = ++generation
    alertLoading.value = true
    alertRule.value = null
    try {
      const [scope, runtimeStatus] = await Promise.all([
        dependencies.fetchProductAlerts(requestedSymbol),
        dependencies.fetchRuntimeStatus(),
      ])
      if (!isCurrent(requestGeneration, requestedSymbol)) return
      alertRule.value = scope.rules.find(
        (rule) => rule.rule_code === 'htdy_original_15m',
      ) ?? null
      alertRuntimeStatus.value = runtimeStatus
    } catch {
      if (!isCurrent(requestGeneration, requestedSymbol)) return
      alertRule.value = null
      alertRuntimeStatus.value = 'failed'
    } finally {
      if (requestGeneration === generation) alertLoading.value = false
    }
  }

  async function toggle(enabled: boolean): Promise<void> {
    const current = alertRule.value
    const requestedSymbol = dependencies.symbol.value
    const requestGeneration = generation
    if (!current || !requestedSymbol || alertSaving.value) return
    alertSaving.value = true
    try {
      const updated = await dependencies.setProductEnabled(
        current.rule_code,
        requestedSymbol,
        enabled,
      )
      if (isCurrentAlertMutation({
        requestGeneration,
        currentGeneration: generation,
        requestedSymbol,
        currentSymbol: dependencies.symbol.value,
        requestedRuleCode: current.rule_code,
        currentRuleCode: alertRule.value?.rule_code,
        updatedRuleCode: updated.rule_code,
      })) {
        alertRule.value = updated
      }
    } catch {
      dependencies.notifyError('Alert Scope 更新失败')
    } finally {
      alertSaving.value = false
    }
  }

  function isCurrent(requestGeneration: number, requestedSymbol: string): boolean {
    return requestGeneration === generation
      && dependencies.symbol.value === requestedSymbol
  }

  function dispose(): void {
    generation += 1
    alertLoading.value = false
    alertSaving.value = false
  }

  return {
    alertRule,
    alertRuntimeStatus,
    alertLoading,
    alertSaving,
    refresh,
    toggle,
    dispose,
  }
}
