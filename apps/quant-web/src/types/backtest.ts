export type BacktestEngineType = 'vnpy'
export type BacktestDataRole = 'primary'
export type BacktestTaskStatus = 'pending' | 'queued' | 'running' | 'success' | 'failed' | 'cancelled' | 'completed' | 'partial_failed'
export type BacktestReportStatus = 'pending' | 'running' | 'success' | 'completed' | 'failed' | 'skipped'

export interface BacktestTaskCreateRequest {
  engine_type?: BacktestEngineType
  task_type?: string
  symbol: string
  exchange: string
  interval: string
  start: string
  end: string
  strategy_class_path: string
  strategy_parameters: Record<string, unknown>
  rate: number
  slippage: number
  size: number
  pricetick: number
  capital: number
  execution_timing?: 'next_bar_open'
  data_source?: string
  data_role?: BacktestDataRole
  data_version?: string | null
  profile_id?: string | null
  market_data_file_id?: number | null
  research_only?: boolean
  quality_status?: string
  request_payload?: Record<string, unknown>
}

export interface BacktestTask {
  id: number
  task_no: string
  task_type: string
  engine_type: string
  status: BacktestTaskStatus
  progress: number
  total_items: number
  completed_items: number
  failed_items: number
  skipped_items: number
  data_source?: string | null
  data_role?: BacktestDataRole | string | null
  data_version?: string | null
  profile_id?: string | null
  market_data_file_id?: number | null
  profile_lineage?: Record<string, unknown> | null
  research_only: boolean
  error_type?: string | null
  error_message?: string | null
  rq_job_id?: string | null
  created_at?: string | null
  started_at?: string | null
  finished_at?: string | null
  result_payload?: Record<string, unknown>
  disclaimer?: string
}

export interface BacktestReportSummary {
  initial_capital?: number
  capital?: number
  final_equity?: number
  ending_equity?: number
  end_balance?: number
  balance?: number
  total_return?: number
  annual_return?: number
  max_drawdown?: number
  max_ddpercent?: number
  max_drawdown_pct?: number
  max_drawdown_amount?: number
  max_margin_required?: number
  max_margin_usage_pct?: number
  rollover_exit_count?: number
  delivery_risk_exit_count?: number
  average_hold_bars?: number | null
  metric_units?: Record<string, string> | null
  win_rate?: number
  profit_loss_ratio?: number
  expectancy?: number
  max_consecutive_losses?: number
  trade_count?: number
  total_trade_count?: number
  total_trades?: number
  total_orders?: number
  filled_orders?: number
  rejected_orders?: number
  total_commission?: number
  total_slippage?: number
  total_net_pnl?: number
  [key: string]: unknown
}

export interface BacktestEquityPoint {
  time?: string
  datetime?: string
  date?: string
  equity?: number
  balance?: number
  cash?: number
  close?: number
  floating_pnl?: number
  margin_used?: number
  position_volume?: number
  [key: string]: unknown
}

export interface BacktestDrawdownPoint {
  time?: string
  datetime?: string
  date?: string
  equity?: number
  peak_equity?: number
  drawdown?: number
  drawdown_pct?: number
  ddpercent?: number
  [key: string]: unknown
}

export interface BacktestOrder {
  order_no?: string
  instrument_symbol?: string
  contract_code?: string
  direction?: string
  offset?: string
  type?: string
  status?: string
  datetime?: string | null
  price?: number
  volume?: number
  traded?: number
  raw_payload?: Record<string, unknown> | null
  [key: string]: unknown
}

export interface BacktestFill {
  [key: string]: unknown
}

export interface BacktestReport {
  id: number
  task_no: string
  report_no: string
  template_name: string
  template_label?: string | null
  engine_type?: string
  engine_version?: string | null
  strategy_code?: string | null
  strategy_version?: string | null
  symbol: string
  contract: string
  period: string
  data_source?: string | null
  data_role?: string | null
  data_version?: string | null
  profile_id?: string | null
  market_data_file_id?: number | null
  profile_lineage?: Record<string, unknown> | null
  research_only?: boolean
  status: BacktestReportStatus
  suitability_label?: string
  suitability_score?: number
  quality_status?: Record<string, unknown>
  initial_capital?: number
  final_equity?: number
  total_return?: number
  annual_return?: number
  max_drawdown?: number
  max_drawdown_pct?: number
  max_drawdown_amount?: number
  max_margin_required?: number | null
  max_margin_usage_pct?: number | null
  win_rate?: number
  profit_loss_ratio?: number
  trade_count?: number
  max_consecutive_losses?: number
  total_commission?: number
  total_slippage?: number
  rollover_exit_count?: number
  delivery_risk_exit_count?: number
  average_hold_bars?: number | null
  metric_units?: Record<string, string> | null
  consistency_hash?: string | null
  summary: BacktestReportSummary
  warnings: string[]
  error_message?: string | null
  created_at?: string | null
  started_at?: string | null
  finished_at?: string | null
  disclaimer?: string
  trades?: BacktestTrade[]
  orders?: BacktestOrder[]
  fills?: BacktestFill[]
  equity_curve?: BacktestEquityPoint[]
  drawdown_curve?: BacktestDrawdownPoint[]
}

export type BacktestTradeDirection = 'long' | 'short' | 'buy' | 'sell' | '多' | '空' | string
export type BacktestTradeSortBy =
  | 'trade_no'
  | 'open_time'
  | 'close_time'
  | 'net_pnl'
  | 'gross_pnl'
  | 'volume'
  | 'commission'
  | 'slippage'
  | 'holding_bars'
export type BacktestTradeSortOrder = 'asc' | 'desc'
export type BacktestTradeExportFormat = 'csv' | 'json'

export interface BacktestTrade {
  id?: number
  report_id?: number
  order_id?: number | string | null
  trade_no: string
  sequence?: number
  instrument_symbol?: string
  exchange?: string
  research_contract?: string
  contract_code?: string
  timeframe?: string
  symbol?: string
  contract?: string
  entry_contract?: string | null
  exit_contract?: string | null
  entry_contract_month?: string | null
  exit_contract_month?: string | null
  direction: BacktestTradeDirection
  entry_signal_time?: string | null
  open_time: string
  open_price: number
  exit_signal_time?: string | null
  close_time: string
  close_price: number
  volume: number
  turnover?: number
  contract_multiplier?: number | null
  price_tick?: number | null
  gross_pnl?: number
  net_pnl: number
  pnl?: number | null
  return_pct?: number
  commission: number
  slippage: number
  margin_ratio?: number | null
  margin_required?: number | null
  balance?: number | null
  equity_after_trade?: number | null
  parameter_source?: string | null
  fee_rule_source?: Record<string, unknown> | null
  main_contract_source?: Record<string, unknown> | null
  rollover_forced_exit?: boolean
  delivery_risk_exit?: boolean
  rollover_reason?: string | null
  holding_bars?: number
  holding_minutes?: number | null
  stop_loss_price?: number | null
  entry_score?: number | null
  entry_grade?: string | null
  long_score?: number | null
  short_score?: number | null
  satisfied_conditions?: string[] | string | null
  failed_conditions?: string[] | string | null
  scene_tags?: string[] | string | null
  skill_notes?: string[] | string | null
  entry_reason?: string
  exit_reason?: string
  remark?: string | null
  note?: string | null
  raw_payload?: Record<string, unknown> | null
}

export interface BacktestTradesQuery {
  limit?: number
  offset?: number
  sort_by?: BacktestTradeSortBy
  sort_order?: BacktestTradeSortOrder
  direction?: string | null
  symbol?: string | null
  contract?: string | null
  start?: string | null
  end?: string | null
}

export interface BacktestTradesPage {
  report_id: number
  total: number
  limit: number
  offset: number
  sort_by?: BacktestTradeSortBy | string
  sort_order?: BacktestTradeSortOrder | string
  filters?: Record<string, unknown>
  items: BacktestTrade[]
}

export interface BacktestTaskForm {
  strategy_code: string
  strategy_version: string
  engine_type: BacktestEngineType
  symbol: string
  exchange: string
  interval: string
  start: number
  end: number
  initial_capital: number
  rate: number
  slippage: number
  size: number
  pricetick: number
  margin_rate: number
  data_role: BacktestDataRole
  profile_id: string
  research_only: boolean
  strategy_params: string
}
