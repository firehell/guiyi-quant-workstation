import type { AlertHistoryResponse } from '../types/market.ts'
import { alertRuleCodeFromWireRecord } from './alertRules.ts'
import { normalizeAlertEventList } from './marketHomeTypes.ts'

export function normalizeAlertHistoryResponse(payload: unknown): AlertHistoryResponse {
  if (!payload || typeof payload !== 'object' || Array.isArray(payload)) throw new Error('alert history must be an object')
  const value = payload as Record<string, unknown>
  if (value.status !== 'ready') throw new Error('alert history status is invalid')
  const startDay = day(value.start_day, 'start_day')
  const endDay = day(value.end_day, 'end_day')
  if (startDay > endDay) throw new Error('alert history range is invalid')
  const symbol = nullableText(value.symbol, 'symbol')?.toLowerCase() ?? null
  const ruleCode = alertRuleCodeFromWireRecord(value)
  const nextBefore = nullableText(value.next_before, 'next_before')
  return {
    status: 'ready', start_day: startDay, end_day: endDay, symbol, rule_code: ruleCode,
    items: normalizeAlertEventList(value.items), next_before: nextBefore,
  }
}

function day(value: unknown, field: string): string {
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value)) throw new Error(`${field} must be an ISO date`)
  const parsed = new Date(`${value}T00:00:00Z`)
  if (!Number.isFinite(parsed.getTime()) || parsed.toISOString().slice(0, 10) !== value) throw new Error(`${field} is invalid`)
  return value
}

function nullableText(value: unknown, field: string): string | null {
  if (value === null) return null
  if (typeof value !== 'string' || !value.trim()) throw new Error(`${field} must be a non-empty string or null`)
  return value
}
