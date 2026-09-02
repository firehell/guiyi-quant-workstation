export interface MarketHomePreferences { version: 1; sector: string; query: string; sort: 'default' | 'change' | 'volume' | 'oi' | 'event' }
export const MARKET_HOME_PREFERENCES_KEY = 'guiyi.market-home.preferences.v1'
const DEFAULT: MarketHomePreferences = { version: 1, sector: '', query: '', sort: 'default' }
export function loadMarketHomePreferences(): MarketHomePreferences { try { const raw = localStorage.getItem(MARKET_HOME_PREFERENCES_KEY); if (!raw) return { ...DEFAULT }; const value = JSON.parse(raw); return value?.version === 1 && typeof value.sector === 'string' && typeof value.query === 'string' && ['default', 'change', 'volume', 'oi', 'event'].includes(value.sort) ? value : { ...DEFAULT } } catch { return { ...DEFAULT } } }
export function saveMarketHomePreferences(value: MarketHomePreferences) { try { localStorage.setItem(MARKET_HOME_PREFERENCES_KEY, JSON.stringify(value)) } catch {} }
