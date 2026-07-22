export type MarketRightRailTab = 'strategy' | 'signal' | 'review' | 'runtime'

const VALID_TABS = new Set<MarketRightRailTab>(['strategy', 'signal', 'review', 'runtime'])
const STORAGE_KEY = 'gy.market.rightRailTab'

export function resolveMarketRightRailTab(input: {
  preferred?: string | null
  hasSignalContext?: boolean
  hasReviewContext?: boolean
}): MarketRightRailTab {
  if (input.hasSignalContext) return 'signal'
  if (input.hasReviewContext) return 'review'
  return VALID_TABS.has(input.preferred as MarketRightRailTab)
    ? input.preferred as MarketRightRailTab
    : 'strategy'
}

export function loadMarketRightRailTab(): MarketRightRailTab {
  if (typeof localStorage === 'undefined') return 'strategy'
  return resolveMarketRightRailTab({ preferred: localStorage.getItem(STORAGE_KEY) })
}

export function saveMarketRightRailTab(tab: MarketRightRailTab) {
  if (typeof localStorage !== 'undefined') localStorage.setItem(STORAGE_KEY, tab)
}
