/** 期货研究面板本地数据覆盖摘要 */
export interface CoverageSummary {
  local_min_date: string | null
  local_max_date: string | null
  requested_start: string
  requested_end: string
  requested_filled: boolean
}

/** 研究面板图表序列定义 */
export interface ChartSeriesSpec {
  name: string
  data: Array<number | string | null>
  yAxisIndex?: number
}

/** 研究面板 ECharts 图表结构 */
export interface ChartSpec {
  chart_type: 'line' | 'step' | 'bar'
  xAxis: string[]
  yAxisCategories?: string[] | null
  series: ChartSeriesSpec[]
}

/** 研究面板表格列定义 */
export interface ColumnSpec {
  key: string
  title: string
  width?: number | null
}

/** 期货研究面板元信息（启用状态、依赖合约、同步脚本等） */
export interface FuturesResearchPanelMeta {
  panel_id: string
  label: string
  description: string
  enabled: boolean
  reason: string | null
  requires_contract: boolean
  sync_script: string | null
  local_coverage_start: string | null
  local_coverage_end: string | null
}

/** 某品种下可用研究面板目录 */
export interface FuturesResearchPanelCatalogResponse {
  symbol: string
  contract: string | null
  panels: FuturesResearchPanelMeta[]
}

/** 单个研究面板的数据响应（图表 + 表格） */
export interface FuturesResearchPanelResponse {
  panel_id: string
  symbol: string
  contract: string | null
  start: string
  end: string
  source: 'local_postgresql'
  provider: string
  data_version: string | null
  row_count: number
  coverage: CoverageSummary
  chart: ChartSpec
  columns: ColumnSpec[]
  rows: Record<string, unknown>[]
  empty_reason: string | null
}

/** 期货研究面板 ID */
export type FuturesResearchPanelId =
  | 'dominant'
  | 'ex-factor'
  | 'trading-parameters'
  | 'warehouse-stocks'
  | 'roll-yield'
  | 'contract-universe'
  | 'continuous-contracts'
  | 'member-rank'

/** 会员持仓排名维度 */
export type MemberRankBy = 'volume' | 'long' | 'short'

/** 期货研究面板查询参数 */
export interface FuturesResearchQuery {
  symbol: string
  contract?: string | null
  start?: string
  end?: string
  rank_by?: MemberRankBy
}
