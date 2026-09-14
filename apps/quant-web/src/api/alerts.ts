import request from './request'
import { getRuntimeHealth } from './runtime'
import type { AlertEvent, AlertHistoryResponse, AlertRuleCode, MarketFrequency } from '@/types/market'
import { normalizeAlertHistoryResponse } from '@/utils/alertHistory'
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

export type { CurrentAlertEventsResponse } from '@/types/market'

export function getCurrentAlertEvents() {
  return request.get<never, unknown>('/api/alerts/current-events', { params: { limit: 30 } })
    .then(normalizeCurrentAlertEventsResponse)
}

export function getProductAlerts(symbol: string) {
  return request.get<never, ProductAlertStateResponse>(`/api/alerts/products/${symbol}`)
}

export function getAlertRuntimeStatus() {
  return getRuntimeHealth().then((response) => response.components.alert.status)
}

export function getAlertEvents(params: { symbol: string; frequency: MarketFrequency; start: string; end: string; ruleCode: AlertRuleCode }) {
  return request.get<never, unknown>('/api/alerts/events', {
    params: { symbol: params.symbol, rule_code: params.ruleCode, frequency: params.frequency, start: params.start, end: params.end },
  }).then(normalizeAlertEventListResponse)
}

export function getAlertHistory(params: { startDay: string; endDay: string; symbol?: string; ruleCode?: AlertRuleCode | null; before?: string | null; limit?: number }, signal?: AbortSignal): Promise<AlertHistoryResponse> {
  return request.get<never, unknown>('/api/alerts/history', {
    params: { start_day: params.startDay, end_day: params.endDay, symbol: params.symbol || undefined, rule_code: params.ruleCode || undefined, before: params.before || undefined, limit: params.limit ?? 30 },
    signal,
  }).then(normalizeAlertHistoryResponse)
}
