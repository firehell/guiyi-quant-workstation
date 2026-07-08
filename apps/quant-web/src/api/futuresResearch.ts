import request from './request'
import type {
  FuturesResearchPanelCatalogResponse,
  FuturesResearchPanelId,
  FuturesResearchPanelResponse,
  FuturesResearchQuery,
  MemberRankBy,
} from '@/types/futuresResearch'

const PANEL_ENDPOINTS: Record<FuturesResearchPanelId, string> = {
  dominant: '/api/v1/market/research/dominant',
  'ex-factor': '/api/v1/market/research/ex-factor',
  'trading-parameters': '/api/v1/market/research/trading-parameters',
  'warehouse-stocks': '/api/v1/market/research/warehouse-stocks',
  'roll-yield': '/api/v1/market/research/roll-yield',
  'contract-universe': '/api/v1/market/research/contract-universe',
  'continuous-contracts': '/api/v1/market/research/continuous-contracts',
  'member-rank': '/api/v1/market/research/member-rank',
}

export function getFuturesResearchPanels(params: { symbol: string; contract?: string | null }) {
  return request.get<any, FuturesResearchPanelCatalogResponse>('/api/v1/market/research/panels', { params })
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
