import request from './request'
import type { AlertRuntimeStatus } from '@/utils/alertControl'
import type { AlertEvent, MarketFrequency } from '@/types/market'

export type { AlertRuntimeStatus } from '@/utils/alertControl'
export type { AlertEvent } from '@/types/market'

export type AlertRuleKind = 'indicator_observation' | 'formal_signal'

export interface ProductAlertRuleState {
  rule_code: string
  display_name: string
  kind: AlertRuleKind
  input_frequencies: MarketFrequency[]
  enabled_for_product: boolean
}

export interface ProductAlertStateResponse {
  symbol: string
  rules: ProductAlertRuleState[]
}

export interface AlertEventListResponse {
  items: AlertEvent[]
}

export interface CurrentFormalSignalItem extends AlertEvent {
  display_name: string
  product_name: string
}

export interface CurrentFormalSignalsResponse {
  status: 'ready' | 'unavailable'
  trading_day: string | null
  items: CurrentFormalSignalItem[]
}

export interface ProductCurrentAlertEventsResponse {
  status: 'ready' | 'unavailable'
  trading_day: string | null
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

export function getCurrentFormalSignals() {
  return request.get<never, CurrentFormalSignalsResponse>('/api/alerts/formal-signals/current')
}

export function getProductCurrentAlertEvents(symbol: string) {
  return request.get<never, ProductCurrentAlertEventsResponse>(
    `/api/alerts/products/${symbol}/current-events`,
  )
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
