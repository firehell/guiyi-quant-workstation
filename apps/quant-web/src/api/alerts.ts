import request from './request'
import type { AlertRuntimeStatus } from '@/utils/alertControl'

export type { AlertRuntimeStatus } from '@/utils/alertControl'

export interface ProductAlertRuleState {
  rule_code: string
  display_name: string
  indicator_code: string
  series_kind: 'actual_dominant'
  frequency: '15m'
  enabled_for_product: boolean
}

export interface ProductAlertStateResponse {
  symbol: string
  rules: ProductAlertRuleState[]
}

interface RuntimeHealthResponse {
  components: {
    alert: {
      status: AlertRuntimeStatus
    }
  }
}

export function getProductAlerts(symbol: string) {
  return request.get<never, ProductAlertStateResponse>(`/api/alerts/products/${symbol}`)
}

export function setAlertProductEnabled(
  ruleCode: string,
  symbol: string,
  enabled: boolean,
) {
  return request.put<never, ProductAlertRuleState>(
    `/api/alerts/rules/${ruleCode}/scope/${symbol}`,
    { enabled },
  )
}

export function getAlertRuntimeStatus() {
  return request.get<never, RuntimeHealthResponse>('/api/runtime/health')
    .then((response) => response.components.alert.status)
}
