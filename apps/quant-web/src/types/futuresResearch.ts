export interface CoverageSummary {
  local_min_date: string | null
  local_max_date: string | null
  requested_start: string
  requested_end: string
  requested_filled: boolean
}

export interface ChartSeriesSpec {
  name: string
  data: Array<number | string | null>
  yAxisIndex?: number
}

export interface ChartSpec {
  chart_type: 'line' | 'step' | 'bar'
  xAxis: string[]
  yAxisCategories?: string[] | null
  series: ChartSeriesSpec[]
}

export interface ColumnSpec {
  key: string
  title: string
  width?: number | null
}

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

export interface FuturesResearchPanelCatalogResponse {
  symbol: string
  contract: string | null
  panels: FuturesResearchPanelMeta[]
}

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

export type FuturesResearchPanelId =
  | 'dominant'
  | 'ex-factor'
  | 'trading-parameters'
  | 'warehouse-stocks'
  | 'roll-yield'
  | 'contract-universe'
  | 'continuous-contracts'
  | 'member-rank'

export type MemberRankBy = 'volume' | 'long' | 'short'

export interface FuturesResearchQuery {
  symbol: string
  contract?: string | null
  start?: string
  end?: string
  rank_by?: MemberRankBy
}
