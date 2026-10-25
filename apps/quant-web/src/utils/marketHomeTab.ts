export type MarketHomeTab = 'market' | 'messages' | 'simnow'
const key = 'guiyi.market-home.tab.v1'
export function loadMarketHomeTab(): MarketHomeTab {
  try { const value = typeof sessionStorage === 'undefined' ? null : sessionStorage.getItem(key); return value === 'messages' || value === 'simnow' ? value : 'market' } catch { return 'market' }
}
export function saveMarketHomeTab(value: MarketHomeTab) { try { if (typeof sessionStorage !== 'undefined') sessionStorage.setItem(key, value) } catch {} }
