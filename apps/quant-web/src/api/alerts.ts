import request from './request'
import { getRuntimeHealth } from './runtime'
import type { AlertEvent, AlertRuleCode, CurrentAlertEventsResponse, MarketFrequency } from '@/types/market'
import {
  normalizeAlertEventListResponse,
  normalizeCurrentAlertEventsResponse,
} from '@/utils/marketHomeTypes'

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
export type ProductCurrentAlertEventsResponse = CurrentAlertEventsResponse

export type { CurrentAlertEventsResponse } from '@/types/market'

export function getCurrentAlertEvents() {
  return request.get<never, unknown>('/api/alerts/current-events', { params: { limit: 30 } })
    .then(normalizeCurrentAlertEventsResponse)
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
  return request.get<never, unknown>(
    `/api/alerts/products/${symbol}/current-events`,
  ).then(normalizeCurrentAlertEventsResponse)
}

export function getAlertEvents(params: { symbol: string; start: string; end: string; ruleCode: AlertRuleCode }) {
  return request.get<never, unknown>('/api/alerts/events', {
    params: { symbol: params.symbol, rule_code: params.ruleCode, start: params.start, end: params.end },
  }).then(normalizeAlertEventListResponse)
}
