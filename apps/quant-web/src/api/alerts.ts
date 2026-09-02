import request from './request'
import { getRuntimeHealth } from './runtime'
import type { AlertEvent, MarketFrequency } from '@/types/market'
import { normalizeCurrentHtdyEventsResponse } from '@/utils/marketHomeTypes'

export type { AlertRuntimeStatus } from '@/utils/alertControl'
export type { AlertEvent } from '@/types/market'
export type AlertRuleKind = 'indicator_observation'

export interface ProductAlertRuleState {
  rule_code: string
  display_name: string
  kind: AlertRuleKind
  input_frequencies: MarketFrequency[]
  enabled_for_product: boolean
  enabled_frequencies: MarketFrequency[]
}

export interface ProductAlertStateResponse { symbol: string; rules: ProductAlertRuleState[] }
export interface AlertEventListResponse { items: AlertEvent[] }
export interface ProductCurrentAlertEventsResponse {
  status: 'ready' | 'unavailable'
  trading_day: string | null
  items: AlertEvent[]
}

export type { CurrentHtdyEventsResponse } from '@/types/market'

export function getCurrentHtdyEvents() {
  return request.get<never, unknown>('/api/alerts/current-events', { params: { limit: 30 } })
    .then(normalizeCurrentHtdyEventsResponse)
}

export function getProductAlerts(symbol: string) {
  return request.get<never, ProductAlertStateResponse>(`/api/alerts/products/${symbol}`)
}

export function setAlertProductFrequencyEnabled(
  ruleCode: string,
  symbol: string,
  frequency: MarketFrequency,
  enabled: boolean,
) {
  return request.put<never, ProductAlertRuleState>(
    `/api/alerts/rules/${ruleCode}/scope/${symbol}/${frequency}`,
    { enabled },
  )
}

export function getAlertRuntimeStatus() {
  return getRuntimeHealth().then((response) => response.components.alert.status)
}

export function getProductCurrentAlertEvents(symbol: string) {
  return request.get<never, ProductCurrentAlertEventsResponse>(
    `/api/alerts/products/${symbol}/current-events`,
  )
}

export function getAlertEvents(params: { symbol: string; start: string; end: string; ruleCode: string }) {
  return request.get<never, AlertEventListResponse>('/api/alerts/events', {
    params: { symbol: params.symbol, rule_code: params.ruleCode, start: params.start, end: params.end },
  })
}
