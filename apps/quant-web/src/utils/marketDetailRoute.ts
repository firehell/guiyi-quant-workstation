import { MARKET_FREQUENCIES, type AlertEvent, type MarketFrequency, type SeriesKind } from '../types/market.ts'
import {
  MARKET_DETAIL_VIEWS,
  type MarketDetailIdentity,
  type MarketDetailRouteErrorCode,
  type MarketDetailRouteResult,
  type MarketDetailView,
  type MarketDetailViewRestore,
} from '../types/marketDetail.ts'
import { isHtdyAlertEvent } from './alertRules.ts'

const SERIES_KINDS = new Set<SeriesKind>(['continuous', 'actual_dominant', 'contract'])
const FREQUENCIES = new Set<MarketFrequency>(MARKET_FREQUENCIES)
const FIXED_IDENTITIES: Record<Extract<MarketDetailView, 'trend' | 'subing'>, Pick<MarketDetailIdentity, 'seriesKind' | 'frequency'>> = {
  trend: { seriesKind: 'actual_dominant', frequency: '1d' },
  subing: { seriesKind: 'actual_dominant', frequency: '15m' },
}

export function parseMarketDetailRoute(query: Record<string, unknown>): MarketDetailRouteResult {
  const viewValue = scalar(query.view)
  const symbol = normalizeSymbol(query.symbol)
  if (viewValue === undefined) return { kind: 'missing-view', symbol }
  if (!isView(viewValue)) return invalid('DETAIL_VIEW_UNKNOWN', symbol, null)
  if (!symbol) return invalid('DETAIL_SYMBOL_INVALID', null, null)

  const fixed = viewValue === 'trend' || viewValue === 'subing' ? FIXED_IDENTITIES[viewValue] : null
  const seriesKind = query.series_kind === undefined && fixed
    ? fixed.seriesKind
    : parseSeriesKind(query.series_kind)
  if (!seriesKind) return invalid('DETAIL_SERIES_KIND_INVALID', symbol, recoveryFor(viewValue, symbol))
  const frequency = query.frequency === undefined && fixed
    ? fixed.frequency
    : parseFrequency(query.frequency)
  if (!frequency) return invalid('DETAIL_FREQUENCY_INVALID', symbol, recoveryFor(viewValue, symbol))

  if (fixed && (seriesKind !== fixed.seriesKind || frequency !== fixed.frequency)) {
    return invalid(viewValue === 'trend' ? 'DETAIL_TREND_IDENTITY_INVALID' : 'DETAIL_SUBING_IDENTITY_INVALID', symbol, {
      view: viewValue, symbol, ...fixed,
    })
  }

  const rawContract = scalar(query.contract)
  if (seriesKind === 'contract') {
    const contract = normalizeContract(rawContract)
    if (!contract) return invalid('DETAIL_CONTRACT_REQUIRED', symbol, recoveryFor(viewValue, symbol))
    if (hasFocus(query) && !allowsFocus(viewValue, seriesKind, frequency)) {
      return invalid('DETAIL_FOCUS_INVALID', symbol, recoveryFor(viewValue, symbol))
    }
    return valid(viewValue, symbol, seriesKind, frequency, contract, query.focus_bar_end)
  }
  if (rawContract !== undefined) return invalid('DETAIL_SERIES_KIND_INVALID', symbol, recoveryFor(viewValue, symbol))
  return valid(viewValue, symbol, seriesKind, frequency, undefined, query.focus_bar_end)
}

export function serializeMarketDetailIdentity(identity: MarketDetailIdentity): Record<string, string | undefined> {
  const focusBarEnd = allowsFocus(identity.view, identity.seriesKind, identity.frequency)
    && isIsoInstant(identity.focusBarEnd)
    ? identity.focusBarEnd
    : undefined
  return {
    view: identity.view,
    symbol: identity.symbol,
    series_kind: identity.seriesKind,
    contract: identity.seriesKind === 'contract' ? identity.contract : undefined,
    frequency: identity.frequency,
    focus_bar_end: focusBarEnd,
  }
}

export function resolveViewSwitchIdentity(
  view: MarketDetailView,
  symbol: string,
  previous: MarketDetailIdentity | null,
  restore: MarketDetailViewRestore,
): MarketDetailIdentity {
  if (view === 'trend' || view === 'subing') return { view, symbol, ...FIXED_IDENTITIES[view] }
  if (previous?.view === view && sameSymbol(previous.symbol, symbol)) {
    if (previous.seriesKind !== 'contract' || previous.contract) {
      return {
        view,
        symbol,
        seriesKind: previous.seriesKind,
        frequency: previous.frequency,
        ...(previous.seriesKind === 'contract' ? { contract: previous.contract } : {}),
      }
    }
  }
  return { view, symbol, ...restore[view] }
}

export function marketDetailEventIdentity(event: AlertEvent): MarketDetailIdentity {
  if (isHtdyAlertEvent(event)) {
    return {
      view: 'htdy', symbol: event.symbol, seriesKind: 'actual_dominant',
      frequency: event.frequency, focusBarEnd: event.bar_end,
    }
  }
  return {
    view: 'subing', symbol: event.symbol, seriesKind: 'actual_dominant',
    frequency: '15m', focusBarEnd: event.bar_end,
  }
}

function valid(
  view: MarketDetailView,
  symbol: string,
  seriesKind: SeriesKind,
  frequency: MarketFrequency,
  contract: string | undefined,
  focus: unknown,
): MarketDetailRouteResult {
  if (focus !== undefined) {
    const focusBarEnd = scalar(focus)
    if (!allowsFocus(view, seriesKind, frequency) || !isIsoInstant(focusBarEnd)) {
      return invalid('DETAIL_FOCUS_INVALID', symbol, recoveryFor(view, symbol))
    }
    return {
      kind: 'valid',
      identity: {
        view, symbol, seriesKind, frequency, focusBarEnd,
        ...(contract ? { contract } : {}),
      },
    }
  }
  return {
    kind: 'valid',
    identity: { view, symbol, seriesKind, frequency, ...(contract ? { contract } : {}) },
  }
}

function invalid(
  code: MarketDetailRouteErrorCode,
  symbol: string | null,
  recovery: MarketDetailIdentity | null,
): MarketDetailRouteResult {
  return { kind: 'invalid', code, recovery: symbol ? recovery : null }
}

function recoveryFor(view: MarketDetailView, symbol: string): MarketDetailIdentity {
  if (view === 'trend' || view === 'subing') return { view, symbol, ...FIXED_IDENTITIES[view] }
  return { view, symbol, seriesKind: 'actual_dominant', frequency: '15m' }
}

function scalar(value: unknown): string | undefined {
  return typeof value === 'string' ? value : undefined
}

function isView(value: string): value is MarketDetailView {
  return (MARKET_DETAIL_VIEWS as readonly string[]).includes(value)
}

function parseSeriesKind(value: unknown): SeriesKind | null {
  const candidate = scalar(value)
  return candidate && SERIES_KINDS.has(candidate as SeriesKind) ? candidate as SeriesKind : null
}

function parseFrequency(value: unknown): MarketFrequency | null {
  const candidate = scalar(value)
  return candidate && FREQUENCIES.has(candidate as MarketFrequency) ? candidate as MarketFrequency : null
}

function normalizeSymbol(value: unknown): string | null {
  const candidate = scalar(value)?.trim().toLowerCase()
  return candidate && /^[a-z]+$/.test(candidate) ? candidate : null
}

function sameSymbol(left: string, right: string): boolean {
  return left.trim().toLowerCase() === right.trim().toLowerCase()
}

function normalizeContract(value: string | undefined): string | null {
  const candidate = value?.trim().toUpperCase()
  return candidate && /^[A-Z]+\d+$/.test(candidate) ? candidate : null
}

function hasFocus(query: Record<string, unknown>): boolean {
  return query.focus_bar_end !== undefined
}

function allowsFocus(view: MarketDetailView, seriesKind: SeriesKind, frequency: MarketFrequency): boolean {
  return (view === 'htdy' && seriesKind === 'actual_dominant')
    || (view === 'subing' && seriesKind === 'actual_dominant' && frequency === '15m')
}

function isIsoInstant(value: string | undefined): value is string {
  if (!value || !/^\d{4}-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/.test(value)) return false
  const parts = value.match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})/)!
  const [year, month, day, hour, minute, second] = parts.slice(1).map(Number)
  const calendar = new Date(Date.UTC(year, month - 1, day))
  return calendar.getUTCFullYear() === year
    && calendar.getUTCMonth() === month - 1
    && calendar.getUTCDate() === day
    && hour <= 23 && minute <= 59 && second <= 59
    && Number.isFinite(Date.parse(value))
}
