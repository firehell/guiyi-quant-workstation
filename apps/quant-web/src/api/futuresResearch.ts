import request from './request'
import type {
  FuturesResearchPanelCatalogResponse,
  FuturesResearchPanelId,
  FuturesResearchPanelResponse,
  FuturesResearchQuery,
  MemberRankBy,
} from '@/types/futuresResearch'

const PANEL_ENDPOINTS: Record<FuturesResearchPanelId, string> = {
  dominant: '/market/research/dominant',
  'ex-factor': '/market/research/ex-factor',
  'trading-parameters': '/market/research/trading-parameters',
  'warehouse-stocks': '/market/research/warehouse-stocks',
  'roll-yield': '/market/research/roll-yield',
  'contract-universe': '/market/research/contract-universe',
  'continuous-contracts': '/market/research/continuous-contracts',
  'member-rank': '/market/research/member-rank',
}

export function getFuturesResearchPanels(params: { symbol: string; contract?: string | null }) {
  return request.get<any, FuturesResearchPanelCatalogResponse>('/market/research/panels', { params })
}

export function getFuturesResearchPanel(panelId: FuturesResearchPanelId, params: FuturesResearchQuery) {
  const endpoint = PANEL_ENDPOINTS[panelId]
  return request.get<any, FuturesResearchPanelResponse>(endpoint, { params })
}

export const MEMBER_RANK_BY_OPTIONS: Array<{ label: string; value: MemberRankBy }> = [
  { label: '成交量', value: 'volume' },
  { label: '持买仓', value: 'long' },
  { label: '持卖仓', value: 'short' },
]
