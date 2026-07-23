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

export interface DashboardLatestSignalEventSummary {
  event_id: number
  event_type: string
  source_mode: string
  lifecycle_status: string
  symbol: string
  contract: string
  period: string
  direction: string
  signal_time?: string | null
}

export interface DashboardLatestReviewSummary {
  review_id: number
  source_type: string
  source_id?: number | null
  symbol?: string | null
  contract?: string | null
  period?: string | null
  review_score?: number | null
  updated_at?: string | null
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
  latest_data_time?: string | null
  latest_confirmed_bar_time?: string | null
  latest_live_signal_event?: DashboardLatestSignalEventSummary | null
  latest_review?: DashboardLatestReviewSummary | null
  unfinished_review_count?: number
  generated_at?: string | null
}

/** 策略注册表中的回测 API 端点描述 */
export interface StrategyBacktestEndpoint {
  label: string
  path: string
  method: string
}

/** 策略 registry 能力分类（machine source 优先） */
export type StrategyRegistryCapabilityClass =
  | 'formal_historical_backtest'
  | 'research_only'
  | 'historical_scan'
  | 'live_observation'
  | 'rejected'
  | 'unavailable'

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
  capability_classes?: StrategyRegistryCapabilityClass[]
  capability_class?: StrategyRegistryCapabilityClass | null
  validation_outcome?: 'rejected' | 'pending' | null
  live_observation?: boolean
}

/** 策略注册表 API 响应 */
export interface StrategyRegistryResponse {
  items: StrategyRegistryItem[]
  total: number
  v1b_count: number
}
