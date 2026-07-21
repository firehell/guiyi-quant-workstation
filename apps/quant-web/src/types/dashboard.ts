/** 仪表盘最近信号扫描任务摘要 */
export interface DashboardScanTaskSummary {
  task_no: string
  status: string
  progress: number
  watchlist_code: string
  created_at?: string | null
}

/** 仪表盘最近 JM 回测报告摘要 */
export interface DashboardLatestReportSummary {
  report_id: number
  report_no: string
  strategy_code?: string | null
  status: string
  created_at?: string | null
}

/** 仪表盘总览统计（数据、风险、策略、信号、回测等） */
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

/** 策略注册表中的回测 API 端点描述 */
export interface StrategyBacktestEndpoint {
  label: string
  path: string
  method: string
}

/** 策略注册表条目（含 V1-B 标记与文档路径） */
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

/** 策略注册表 API 响应 */
export interface StrategyRegistryResponse {
  items: StrategyRegistryItem[]
  total: number
  v1b_count: number
}
