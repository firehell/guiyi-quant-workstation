import type { LocationQuery } from 'vue-router'
import type { MarketFrequency, ResearchOverlayId, SeriesKind } from '@/types/market'

export type SubingConfirmEntryKind = 'subing-daily-watch' | 'subing-strategy-action'

export interface SubingConfirmChartEntry {
  symbol: string
  seriesKind: 'actual_dominant'
  frequency: '15m'
  overlay: 'subing'
  entry: SubingConfirmEntryKind
  actionId?: string
}

export type SubingDailyWatchChartEntry = Omit<SubingConfirmChartEntry, 'entry' | 'actionId'> & {
  overlay: 'subing'
}

function queryString(value: LocationQuery[string]): string | null {
  return typeof value === 'string' ? value : null
}

function parseSymbol(value: LocationQuery[string]): string | null {
  const raw = queryString(value)
  if (raw === null) return null
  const symbol = raw.trim().toLowerCase()
  return /^[a-z]+$/.test(symbol) ? symbol : null
}

function parseActionId(value: LocationQuery[string]): string | null {
  const raw = queryString(value)
  if (raw === null) return null
  const actionId = raw.trim()
  return actionId.startsWith('subing-action:') ? actionId : null
}

function hasContract(query: LocationQuery): boolean {
  const contract = query.contract
  return contract !== undefined && contract !== null && contract !== ''
}

function matchesSubingConfirmIdentity(query: LocationQuery): boolean {
  return query.overlay === 'subing'
    && query.series_kind === 'actual_dominant'
    && query.frequency === '15m'
    && !hasContract(query)
}

export function resolveSubingConfirmChartEntry(
  query: LocationQuery,
): SubingConfirmChartEntry | null {
  if (!matchesSubingConfirmIdentity(query)) return null
  const symbol = parseSymbol(query.symbol)
  if (symbol === null) return null

  if (query.entry === 'subing-daily-watch') {
    if (query.action_id !== undefined && query.action_id !== null && query.action_id !== '') {
      return null
    }
    return {
      symbol,
      seriesKind: 'actual_dominant',
      frequency: '15m',
      overlay: 'subing',
      entry: 'subing-daily-watch',
    }
  }

  if (query.entry === 'subing-strategy-action') {
    const actionId = parseActionId(query.action_id)
    if (actionId === null) return null
    return {
      symbol,
      seriesKind: 'actual_dominant',
      frequency: '15m',
      overlay: 'subing',
      entry: 'subing-strategy-action',
      actionId,
    }
  }

  return null
}

export function resolveSubingDailyWatchChartEntry(
  query: LocationQuery,
): SubingDailyWatchChartEntry | null {
  const resolved = resolveSubingConfirmChartEntry(query)
  if (resolved === null || resolved.entry !== 'subing-daily-watch') return null
  return {
    symbol: resolved.symbol,
    seriesKind: resolved.seriesKind,
    frequency: resolved.frequency,
    overlay: resolved.overlay,
  }
}

export function seriesRefreshQuery(input: {
  symbol: string
  contract: string
  seriesKind: SeriesKind
  frequency: MarketFrequency
  overlay: ResearchOverlayId
  confirm: SubingConfirmChartEntry | null
}): Record<string, string | undefined> {
  const identity: Record<string, string | undefined> = {
    symbol: input.symbol,
    contract: input.seriesKind === 'contract' && input.contract ? input.contract : undefined,
    series_kind: input.seriesKind,
    frequency: input.frequency,
  }
  const confirm = input.confirm
  if (
    confirm === null
    || input.overlay !== 'subing'
    || input.seriesKind !== 'actual_dominant'
    || input.frequency !== '15m'
    || input.symbol !== confirm.symbol
  ) {
    return identity
  }
  return {
    ...identity,
    overlay: 'subing',
    entry: confirm.entry,
    action_id: confirm.actionId,
  }
}
