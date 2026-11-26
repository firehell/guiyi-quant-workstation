import type { CanonicalBarDto, MarketBarsPageResponse, MarketBarsPageWireResponse, MarketTickQuote } from '../types/market.ts'

const DECIMAL = /^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$/

/** Convert transport precision only for display/chart consumers, never authoritative returns. */
export function normalizeMarketBarWire(payload: unknown, field = 'bar'): CanonicalBarDto {
  if (payload === null || typeof payload !== 'object' || Array.isArray(payload)) throw new Error(`${field} must be an object`)
  const value = payload as Record<string, unknown>
  const sourceHash = value.source_bar_sha256
  if (sourceHash !== undefined && (typeof sourceHash !== 'string' || !/^[a-f0-9]{64}$/.test(sourceHash))) {
    throw new Error('Invalid Canonical Bar fingerprint')
  }
  return {
    bar_end: value.bar_end as string,
    trading_day: value.trading_day as string,
    open: displayNumber(value.open, `${field}.open`),
    high: displayNumber(value.high, `${field}.high`),
    low: displayNumber(value.low, `${field}.low`),
    close: displayNumber(value.close, `${field}.close`),
    volume: displayNumber(value.volume, `${field}.volume`),
    ...(sourceHash !== undefined ? { source_bar_sha256: sourceHash } : {}),
    turnover: nullableDisplayNumber(value.turnover, `${field}.turnover`),
    open_interest: nullableDisplayNumber(value.open_interest, `${field}.open_interest`),
  }
}

export function normalizeMarketTickQuoteWire(payload: unknown): MarketTickQuote {
  if (payload === null || typeof payload !== 'object' || Array.isArray(payload)) throw new Error('Invalid Tick quote')
  const quote = payload as MarketTickQuote
  if (quote.stale !== undefined && typeof quote.stale !== 'boolean') throw new Error('Invalid Tick quote freshness')
  if (typeof quote.last_price !== 'string' || displayNumber(quote.last_price, 'quote.last_price') <= 0) throw new Error('Invalid Tick price')
  for (const levels of [quote.bids, quote.asks]) {
    if (!Array.isArray(levels) || levels.length > 5) throw new Error('Invalid order book')
    for (const pair of levels) {
      if (!Array.isArray(pair) || pair.length !== 2 || !pair.every(value => typeof value === 'string')
        || displayNumber(pair[0], 'quote.price') <= 0 || displayNumber(pair[1], 'quote.size') < 0) {
        throw new Error('Invalid order book level')
      }
    }
  }
  return quote
}

export function normalizeMarketBarsPageResponse(payload: unknown): MarketBarsPageResponse {
  if (payload === null || typeof payload !== 'object' || Array.isArray(payload)) throw new Error('market bars page must be an object')
  const value = payload as unknown as MarketBarsPageWireResponse
  if (!Array.isArray(value.bars)) throw new Error('bars must be an array')
  return { ...value, bars: value.bars.map((bar, index) => normalizeMarketBarWire(bar, `bars[${index}]`)) }
}

function displayNumber(value: unknown, field: string): number {
  if (typeof value === 'number') {
    if (Number.isFinite(value)) return value
    throw new Error(`${field} must be finite`)
  }
  if (typeof value !== 'string' || !DECIMAL.test(value)) throw new Error(`${field} must be a finite number or Decimal string`)
  const normalized = Number(value)
  if (!Number.isFinite(normalized)) throw new Error(`${field} must be finite`)
  return normalized
}

function nullableDisplayNumber(value: unknown, field: string): number | null {
  return value === null ? null : displayNumber(value, field)
}
