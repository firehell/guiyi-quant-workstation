import type { ProductResearchResponse } from '../types/market.ts'
import type { DetailViewModel, MarketDetailHeaderModel, MarketDetailIdentity } from '../types/marketDetail.ts'

export function buildFreeDetailViewModel(input: {
  identity: MarketDetailIdentity
  header: MarketDetailHeaderModel
  research: ProductResearchResponse | null
  researchError: boolean
  rangeState: 'disabled' | 'loading' | 'ready' | 'insufficient'
}): DetailViewModel {
  const dataStatus = input.header.freshness === 'fresh'
    ? 'ready'
    : input.header.freshness === 'stale' ? 'stale' : 'unavailable'
  const rangeRisk = 'Range Detector 只读回画展示；确认前不可用于策略判断。'
  const rangeMessage = input.rangeState === 'ready'
    ? rangeRisk
    : input.rangeState === 'loading'
      ? `箱体历史预载中；${rangeRisk}`
      : input.rangeState === 'insufficient'
        ? `箱体历史预载不足；${rangeRisk}`
        : null
  const semanticStatement = '自由看盘仅提供行情与通用指标复核，不生成策略结论。'
  return {
    view: 'free',
    identity: input.identity,
    asOf: input.header.asOf,
    semanticBanner: {
      text: rangeMessage
        ? `${rangeMessage}；${semanticStatement}`
        : input.researchError ? `市场背景暂不可用；${semanticStatement}` : semanticStatement,
      tone: rangeMessage || input.researchError ? 'warning' : 'info',
    },
    facts: [
      fact('series', '当前序列', seriesKindText(input.identity.seriesKind), 'market'),
      fact('frequency', '当前周期', frequencyText(input.identity.frequency), 'market'),
      fact('data-status', '数据状态', dataStatusText(dataStatus), dataStatus === 'ready' ? 'market' : 'market', dataStatus === 'ready' ? 'default' : dataStatus === 'stale' ? 'warning' : 'unavailable'),
    ],
    disclosureSections: input.header.extendedSections,
    history: [],
    dataStatus,
  }
}

function fact(
  id: string,
  label: string,
  value: string,
  source: 'market',
  tone: 'default' | 'warning' | 'unavailable' = 'default',
) {
  return { id, label, value, source, tone } as const
}

function seriesKindText(value: MarketDetailIdentity['seriesKind']): string {
  if (value === 'continuous') return '主连'
  if (value === 'contract') return '指定合约'
  return '真实主力'
}

function dataStatusText(value: DetailViewModel['dataStatus']): string {
  if (value === 'ready') return '正常'
  if (value === 'stale') return '旧快照'
  return '不可用'
}

function frequencyText(value: MarketDetailIdentity['frequency']): string {
  if (value === '1d') return '日K'
  if (value === '1w') return '周K'
  return `${value.slice(0, -1)}分钟`
}
