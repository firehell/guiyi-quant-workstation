import request from './request'
import type { AlertRuntimeStatus } from '@/utils/alertControl'
import type { AlertEvent } from '@/types/market'

export type { AlertRuntimeStatus } from '@/utils/alertControl'
export type { AlertEvent } from '@/types/market'

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

export interface AlertEventListResponse {
  items: AlertEvent[]
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

export function getAlertEvents(params: {
  symbol: string
  start: string
  end: string
  ruleCode?: string
}) {
  return request.get<never, AlertEventListResponse>('/api/alerts/events', {
    params: {
      symbol: params.symbol,
      rule_code: params.ruleCode || 'htdy_original_15m',
      start: params.start,
      end: params.end,
    },
  })
}
