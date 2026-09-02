import type {
  CurrentHtdyEventsResponse,
  MarketFrequency,
  MarketHomeOverviewResponse,
  MarketHomeTrend,
} from '../types/market.ts'
import { HTDY_ALERT_RULE_CODE } from './alertRules.ts'

const MARKET_FREQUENCIES = new Set<MarketFrequency>(['1m', '5m', '15m', '30m', '60m', '1d', '1w'])
const MARKET_TRENDS = new Set<MarketHomeTrend>(['up', 'down', 'neutral', 'unavailable'])

export function normalizeMarketHomeOverviewResponse(payload: unknown): MarketHomeOverviewResponse {
  const value = record(payload, 'market home overview')
  const items = array(value.items, 'items').map((item, index) => normalizeItem(item, index))
  const participantCount = count(value.participant_count, 'participant_count')
  const activeCount = count(value.active_count, 'active_count')
  const staleCount = count(value.stale_count, 'stale_count')
  const unavailableCount = count(value.unavailable_count, 'unavailable_count')
  const symbols = new Set(items.map((item) => item.symbol))
  if (symbols.size !== items.length) throw new Error('market home items contain duplicate symbols')
  if (participantCount !== items.length || activeCount !== participantCount + staleCount + unavailableCount) throw new Error('market home counts are inconsistent')
  const targetAsOf = day(value.target_as_of, 'target_as_of')
  const dataAsOf = day(value.data_as_of, 'data_as_of')
  if (items.some((item) => item.data_as_of !== dataAsOf)) throw new Error('market home items disagree on data_as_of')
  const summary = normalizeSummary(value.summary, participantCount)
  const sectors = array(value.sectors, 'sectors').map((sector, index) => normalizeSector(sector, index))
  if (new Set(sectors.map((sector) => sector.sector)).size !== sectors.length || sectors.reduce((total, sector) => total + sector.active_count, 0) !== activeCount || sectors.reduce((total, sector) => total + sector.participant_count, 0) !== participantCount) throw new Error('market home sectors are inconsistent')
  return { status: literal(value.status, ['ready', 'degraded'], 'status'), target_as_of: targetAsOf, data_as_of: dataAsOf, freshness: literal(value.freshness, ['fresh', 'stale', 'unavailable'], 'freshness'), active_count: activeCount, participant_count: participantCount, stale_count: staleCount, unavailable_count: unavailableCount, summary, items, sectors }
}

export function normalizeCurrentHtdyEventsResponse(payload: unknown): CurrentHtdyEventsResponse {
  const value = record(payload, 'current HTDY events')
  const status = literal(value.status, ['ready', 'unavailable'], 'status')
  const items = array(value.items, 'items').map((item, index) => normalizeEvent(item, index))
  const tradingDay = nullableDay(value.trading_day, 'trading_day')
  if (new Set(items.map((item) => item.id)).size !== items.length) throw new Error('current HTDY events contain duplicate ids')
  if (status === 'unavailable') {
    if (tradingDay !== null || items.length) throw new Error('unavailable current HTDY events must be empty')
  } else if (tradingDay === null || items.some((item) => item.trading_day !== tradingDay)) throw new Error('ready current HTDY events must use one trading day')
  return { status, trading_day: tradingDay, items }
}

function normalizeItem(payload: unknown, index: number): MarketHomeOverviewResponse['items'][number] {
  const value = record(payload, `items[${index}]`)
  return { symbol: text(value.symbol, 'symbol').toLowerCase(), product_name: text(value.product_name, 'product_name'), sector: text(value.sector, 'sector'), exchange: text(value.exchange, 'exchange'), actual_contract: text(value.actual_contract, 'actual_contract'), dominant_mapping_date: day(value.dominant_mapping_date, 'dominant_mapping_date'), data_as_of: day(value.data_as_of, 'data_as_of'), close: requiredDecimal(value.close, 'close'), price_change_1d: decimal(value.price_change_1d, 'price_change_1d'), price_change_5d: decimal(value.price_change_5d, 'price_change_5d'), volume_ratio20: decimal(value.volume_ratio20, 'volume_ratio20'), oi_change_1d: decimal(value.oi_change_1d, 'oi_change_1d'), atr14_percentile252: decimal(value.atr14_percentile252, 'atr14_percentile252'), daily_trend: literal(value.daily_trend, [...MARKET_TRENDS], 'daily_trend'), weekly_trend: literal(value.weekly_trend, [...MARKET_TRENDS], 'weekly_trend'), reason_codes: array(value.reason_codes, 'reason_codes').map((reason) => text(reason, 'reason_code')) }
}

function normalizeSummary(payload: unknown, participantCount: number): MarketHomeOverviewResponse['summary'] {
  const value = record(payload, 'summary')
  const summary = { price_up_count: count(value.price_up_count, 'price_up_count'), price_down_count: count(value.price_down_count, 'price_down_count'), price_flat_count: count(value.price_flat_count, 'price_flat_count'), daily_up_count: count(value.daily_up_count, 'daily_up_count'), daily_down_count: count(value.daily_down_count, 'daily_down_count'), daily_neutral_count: count(value.daily_neutral_count, 'daily_neutral_count'), daily_unavailable_count: count(value.daily_unavailable_count, 'daily_unavailable_count'), aligned_up_count: count(value.aligned_up_count, 'aligned_up_count'), aligned_down_count: count(value.aligned_down_count, 'aligned_down_count') }
  if (summary.price_up_count + summary.price_down_count + summary.price_flat_count !== participantCount || summary.daily_up_count + summary.daily_down_count + summary.daily_neutral_count + summary.daily_unavailable_count !== participantCount || summary.aligned_up_count + summary.aligned_down_count > participantCount) throw new Error('market home summary is inconsistent')
  return summary
}

function normalizeSector(payload: unknown, index: number): MarketHomeOverviewResponse['sectors'][number] {
  const value = record(payload, `sectors[${index}]`)
  const activeCount = count(value.active_count, 'sector.active_count')
  const participantCount = count(value.participant_count, 'sector.participant_count')
  if (participantCount > activeCount) throw new Error('sector participant_count exceeds active_count')
  return { sector: text(value.sector, 'sector'), active_count: activeCount, participant_count: participantCount, median_price_change_1d: decimal(value.median_price_change_1d, 'median_price_change_1d') }
}

function normalizeEvent(payload: unknown, index: number): CurrentHtdyEventsResponse['items'][number] {
  const value = record(payload, `items[${index}]`)
  const resultCodes: Array<'buy' | 'sell'> = array(value.result_codes, 'result_codes').map((code) => literal(code, ['buy', 'sell'] as const, 'result_code'))
  if (!resultCodes.length || new Set(resultCodes).size !== resultCodes.length) throw new Error('result_codes are invalid')
  return { id: positiveId(value.id), rule_code: literal(field(value, 'rule_code'), [HTDY_ALERT_RULE_CODE], 'rule_code'), symbol: text(value.symbol, 'symbol').toLowerCase(), contract: text(value.contract, 'contract'), trading_day: nullableDay(value.trading_day, 'trading_day'), frequency: literal(value.frequency, [...MARKET_FREQUENCIES], 'frequency'), bar_end: instant(value.bar_end, 'bar_end'), result_codes: resultCodes, detected_at: instant(value.detected_at, 'detected_at'), notification_attempted_at: nullableInstant(value.notification_attempted_at, 'notification_attempted_at') }
}

function record(value: unknown, field: string): Record<string, unknown> { if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error(`${field} must be an object`); return value as Record<string, unknown> }
function field(value: Record<string, unknown>, key: string): unknown { return value[key] }
function array(value: unknown, field: string): unknown[] { if (!Array.isArray(value)) throw new Error(`${field} must be an array`); return value }
function text(value: unknown, field: string): string { if (typeof value !== 'string' || !value.trim()) throw new Error(`${field} must be a non-empty string`); return value }
function decimal(value: unknown, field: string): number | null { if (value === null) return null; if (typeof value !== 'string' || !value.trim()) throw new Error(`${field} must be a Decimal string or null`); const normalized = Number(value); if (!Number.isFinite(normalized)) throw new Error(`${field} must be finite`); return normalized }
function requiredDecimal(value: unknown, field: string): number { const normalized = decimal(value, field); if (normalized === null) throw new Error(`${field} must be a Decimal string`); return normalized }
function count(value: unknown, field: string): number { if (typeof value !== 'number' || !Number.isInteger(value) || value < 0) throw new Error(`${field} must be a non-negative integer`); return value }
function positiveId(value: unknown): number { if (typeof value !== 'number' || !Number.isInteger(value) || value <= 0) throw new Error('id must be a positive integer'); return value }
function literal<T extends string>(value: unknown, values: readonly T[], field: string): T { if (typeof value !== 'string' || !values.includes(value as T)) throw new Error(`${field} is invalid`); return value as T }
function day(value: unknown, field: string): string { if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value)) throw new Error(`${field} must be an ISO date`); const parsed = new Date(`${value}T00:00:00Z`); if (!Number.isFinite(parsed.getTime()) || parsed.toISOString().slice(0, 10) !== value) throw new Error(`${field} is invalid`); return value }
function nullableDay(value: unknown, field: string): string | null { return value === null ? null : day(value, field) }
function instant(value: unknown, field: string): string { if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}T.*(?:Z|[+-]\d{2}:?\d{2})$/.test(value)) throw new Error(`${field} must be an ISO instant with timezone`); day(value.slice(0, 10), field); if (!Number.isFinite(Date.parse(value))) throw new Error(`${field} must be an ISO instant with timezone`); return value }
function nullableInstant(value: unknown, field: string): string | null { return value === null ? null : instant(value, field) }
