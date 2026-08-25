import type { MarketFrequency, SeriesKind } from '@/types/market'

export const MARKET_WORKSPACE_PREFERENCES_KEY = 'guiyi.market.workspace.preferences.v1'
export const MARKET_WORKSPACE_PREFERENCES_VERSION = 1

const VALID_FREQUENCIES = new Set<MarketFrequency>(['1m', '5m', '15m', '30m', '60m', '1d', '1w'])

export interface MarketWorkspacePreferences {
  version: 1
  symbol: string | null
  seriesKind: Extract<SeriesKind, 'actual_dominant' | 'continuous'>
  frequency: MarketFrequency
  researchSidebarOpen: boolean
}

type WorkspaceStorage = Pick<Storage, 'getItem' | 'setItem'>

export function defaultMarketWorkspacePreferences(): MarketWorkspacePreferences {
  return {
    version: 1,
    symbol: null,
    seriesKind: 'actual_dominant',
    frequency: '15m',
    researchSidebarOpen: true,
  }
}

export function loadMarketWorkspacePreferences(
  storage: Pick<WorkspaceStorage, 'getItem'> | null = browserStorage(),
): MarketWorkspacePreferences {
  if (!storage) return defaultMarketWorkspacePreferences()
  try {
    const raw = storage.getItem(MARKET_WORKSPACE_PREFERENCES_KEY)
    if (!raw) return defaultMarketWorkspacePreferences()
    const parsed = JSON.parse(raw) as Partial<MarketWorkspacePreferences> | null
    if (!parsed || parsed.version !== MARKET_WORKSPACE_PREFERENCES_VERSION) {
      return defaultMarketWorkspacePreferences()
    }
    return {
      version: 1,
      symbol: normalizeSymbol(parsed.symbol),
      seriesKind: parsed.seriesKind === 'continuous' ? 'continuous' : 'actual_dominant',
      frequency: normalizeFrequency(parsed.frequency),
      researchSidebarOpen: typeof parsed.researchSidebarOpen === 'boolean'
        ? parsed.researchSidebarOpen
        : true,
    }
  } catch {
    return defaultMarketWorkspacePreferences()
  }
}

export function saveMarketWorkspacePreferences(
  preferences: MarketWorkspacePreferences,
  storage: Pick<WorkspaceStorage, 'setItem'> | null = browserStorage(),
): void {
  if (!storage) return
  try {
    storage.setItem(MARKET_WORKSPACE_PREFERENCES_KEY, JSON.stringify({
      version: 1,
      symbol: normalizeSymbol(preferences.symbol),
      seriesKind: preferences.seriesKind === 'continuous' ? 'continuous' : 'actual_dominant',
      frequency: normalizeFrequency(preferences.frequency),
      researchSidebarOpen: Boolean(preferences.researchSidebarOpen),
    }))
  } catch {
    // localStorage 不可用不能阻塞 Market 工作台。
  }
}

function normalizeSymbol(value: unknown): string | null {
  if (typeof value !== 'string') return null
  const normalized = value.trim().toLowerCase()
  return /^[a-z]+$/.test(normalized) ? normalized : null
}

function normalizeFrequency(value: unknown): MarketFrequency {
  return typeof value === 'string' && VALID_FREQUENCIES.has(value as MarketFrequency)
    ? value as MarketFrequency
    : '15m'
}

function browserStorage(): WorkspaceStorage | null {
  return typeof window === 'undefined' ? null : window.localStorage
}
