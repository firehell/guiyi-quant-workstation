import type { MarketHomeLiveFrame, MarketHomeLiveItem, MarketHomeLiveAvailability, MarketHomeLivePhase, MarketHomeLiveSource } from '../types/market.ts'

const SOURCES: MarketHomeLiveSource[] = ['completed_1m', 'completed_1d', 'none']
const AVAILABILITIES: MarketHomeLiveAvailability[] = ['live', 'historical', 'unavailable']
const PHASES: MarketHomeLivePhase[] = ['TRADING', 'BREAK', 'CLOSED', 'UNKNOWN']

export function normalizeMarketHomeLiveFrame(payload: unknown): MarketHomeLiveFrame {
  const value = record(payload, 'frame')
  if (value.schema_version !== 1) throw new Error('market home live schema_version is invalid')
  const observedAt = instant(value.observed_at, 'observed_at')
  if (value.type === 'snapshot') {
    if (value.scope !== 'operational') throw new Error('market home live scope is invalid')
    return { type: 'snapshot', schemaVersion: 1, observedAt, scope: 'operational', items: items(value.items) }
  }
  if (value.type === 'quote') return { type: 'quote', schemaVersion: 1, observedAt, item: item(value.item) }
  if (value.type === 'reset') {
    if (value.reason !== 'AUTHORITY_CHANGED') throw new Error('market home live reset reason is invalid')
    return { type: 'reset', schemaVersion: 1, observedAt, reason: value.reason, items: items(value.items) }
  }
  if (value.type === 'unavailable' && value.code === 'MARKET_HOME_LIVE_UNAVAILABLE') return { type: 'unavailable', schemaVersion: 1, observedAt, code: value.code }
  throw new Error('market home live frame type is invalid')
}

function items(value: unknown): MarketHomeLiveItem[] {
  if (!Array.isArray(value)) throw new Error('items must be an array')
  const normalized = value.map(item)
  if (new Set(normalized.map((entry) => entry.symbol)).size !== normalized.length) throw new Error('market home live symbols must be unique')
  return normalized
}

function item(payload: unknown): MarketHomeLiveItem {
  const value = record(payload, 'item')
  const source = literal(value.source, SOURCES, 'source')
  const availability = literal(value.availability, AVAILABILITIES, 'availability')
  const physicalContract = nullableText(value.physical_contract, 'physical_contract')?.toUpperCase() ?? null
  const tradingDay = value.trading_day === null ? null : day(value.trading_day, 'trading_day')
  const barEnd = value.bar_end === null ? null : instant(value.bar_end, 'bar_end')
  const price = decimal(value.price, 'price')
  const previousClose = decimal(value.previous_close, 'previous_close')
  const priceChange = decimal(value.price_change, 'price_change')
  const reason = nullableText(value.reason, 'reason')
  if (availability === 'unavailable' && reason === null) throw new Error('unavailable live item requires a reason')
  if ((source === 'completed_1m') !== (availability === 'live')) throw new Error('completed_1m must be a live value')
  if ((source === 'completed_1d') !== (availability === 'historical')) throw new Error('completed_1d must be a historical value')
  if ((source === 'none') !== (availability === 'unavailable')) throw new Error('none source must be unavailable')
  if (source === 'none' && [physicalContract, tradingDay, barEnd, price, previousClose, priceChange].some((entry) => entry !== null)) throw new Error('none source cannot carry a completed value')
  if (source !== 'none' && (physicalContract === null || tradingDay === null || barEnd === null || price === null)) throw new Error('completed source requires a complete identity and price')
  if (priceChange !== null && (previousClose === null || previousClose === 0 || physicalContract === null)) throw new Error('price_change requires a nonzero same-contract baseline')
  return { symbol: text(value.symbol, 'symbol').toLowerCase(), physicalContract, tradingDay, barEnd, price, previousClose, priceChange, source, availability, phase: literal(value.phase, PHASES, 'phase'), reason }
}

function record(value: unknown, field: string): Record<string, unknown> { if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error(`${field} must be an object`); return value as Record<string, unknown> }
function text(value: unknown, field: string): string { if (typeof value !== 'string' || !value.trim()) throw new Error(`${field} must be a non-empty string`); return value }
function nullableText(value: unknown, field: string): string | null { if (value === null) return null; return text(value, field) }
function decimal(value: unknown, field: string): number | null { if (value === null) return null; if (typeof value !== 'string' || !value.trim()) throw new Error(`${field} must be a Decimal string or null`); const normalized = Number(value); if (!Number.isFinite(normalized)) throw new Error(`${field} must be finite`); return normalized }
function literal<T extends string>(value: unknown, allowed: readonly T[], field: string): T { if (typeof value !== 'string' || !allowed.includes(value as T)) throw new Error(`${field} is invalid`); return value as T }
function day(value: unknown, field: string): string { if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value)) throw new Error(`${field} must be an ISO date`); const parsed = new Date(`${value}T00:00:00Z`); if (!Number.isFinite(parsed.getTime()) || parsed.toISOString().slice(0, 10) !== value) throw new Error(`${field} is invalid`); return value }
function instant(value: unknown, field: string): string { if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}T.*(?:Z|[+-]\d{2}:?\d{2})$/.test(value) || !Number.isFinite(Date.parse(value))) throw new Error(`${field} must be an ISO instant`); return value }
