export interface DashboardScanTaskSummary {
  task_no: string
  status: string
  progress: number
  watchlist_code: string
  created_at?: string | null
}

export interface DashboardLatestReportSummary {
  report_id: number
  report_no: string
  strategy_code?: string | null
  status: string
  created_at?: string | null
}

export interface DashboardSummary {
  data_status: string
  risk_status: string
  strategies: number
  v1b_strategies: number
  signals_today: number
  signals_week: number
  backtests: number
  backtest_reports: number
  backtest_reports_success: number
  data_contracts: number
  jm_primary_passed_assets: number
  live_target_readiness?: string | null
  live_targets_preview_only: boolean
  latest_scan_task?: DashboardScanTaskSummary | null
  latest_jm_report?: DashboardLatestReportSummary | null
  generated_at?: string | null
}

export interface StrategyBacktestEndpoint {
  label: string
  path: string
  method: string
}

export interface StrategyRegistryItem {
  strategy_code: string
  name: string
  description: string
  symbol?: string | null
  product?: string | null
  periods: string[]
  is_v1b: boolean
  backtest_endpoints: StrategyBacktestEndpoint[]
  scan_endpoint?: string | null
  strategy_version?: string | null
  spec_doc_path?: string | null
  spec_doc_exists: boolean
}

export interface StrategyRegistryResponse {
  items: StrategyRegistryItem[]
  total: number
  v1b_count: number
}
