import type { MarketFrequency } from '../types/market.ts'

export interface MarketHomePreferences { version: 1; sector: string; sort: 'default' | 'change' | 'volume' | 'oi' | 'event'; compactDensity: boolean; detailFrequency: MarketFrequency; focusRailCollapsed: boolean }
export const MARKET_HOME_PREFERENCES_KEY = 'guiyi.market-home.preferences.v1'
const DEFAULT: MarketHomePreferences = { version: 1, sector: '', sort: 'default', compactDensity: false, detailFrequency: '1d', focusRailCollapsed: false }
export function loadMarketHomePreferences(): MarketHomePreferences { try { const raw = localStorage.getItem(MARKET_HOME_PREFERENCES_KEY); if (!raw) return { ...DEFAULT }; const value = JSON.parse(raw); return value?.version === 1 && typeof value.sector === 'string' && ['default', 'change', 'volume', 'oi', 'event'].includes(value.sort) && typeof value.compactDensity === 'boolean' && ['1m','5m','15m','30m','60m','1d','1w'].includes(value.detailFrequency) && typeof value.focusRailCollapsed === 'boolean' ? value : { ...DEFAULT } } catch { return { ...DEFAULT } } }
export function saveMarketHomePreferences(value: MarketHomePreferences) { try { localStorage.setItem(MARKET_HOME_PREFERENCES_KEY, JSON.stringify(value)) } catch {} }
