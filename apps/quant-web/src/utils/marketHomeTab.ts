export type MarketHomeTab = 'market' | 'messages' | 'simulation'
const key = 'guiyi.market-home.tab.v1'
export function loadMarketHomeTab(): MarketHomeTab {
  try { const value = typeof sessionStorage === 'undefined' ? null : sessionStorage.getItem(key); return value === 'messages' || value === 'simulation' ? value : 'market' } catch { return 'market' }
}
export function saveMarketHomeTab(value: MarketHomeTab) { try { if (typeof sessionStorage !== 'undefined') sessionStorage.setItem(key, value) } catch {} }
