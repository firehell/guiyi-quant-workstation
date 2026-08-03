/** 策略信息 */
export interface StrategyInfo {
  id: string
  name: string
  type: 'trend' | 'mean_reversion' | 'arbitrage' | 'pattern'
  description: string
  status: 'running' | 'stopped' | 'error'
  params: Record<string, unknown>
  createdAt: string
  updatedAt: string
}

/** 回测结果 */
export interface BacktestResult {
  backtestId: string
  strategyId: string
  symbol: string
  startDate: string
  endDate: string
  metrics: BacktestMetrics
  equityCurve: EquityPoint[]
  trades: TradeRecord[]
}

/** 回测绩效指标 */
export interface BacktestMetrics {
  totalReturn: number
  annualReturn: number
  maxDrawdown: number
  sharpeRatio: number
  sortinoRatio: number
  winRate: number
  profitFactor: number
  totalTrades: number
  avgHoldDays: number
}

/** 权益曲线点 */
export interface EquityPoint {
  date: string
  equity: number
  drawdown: number
}

/** 交易记录 */
export interface TradeRecord {
  tradeId: string
  symbol: string
  direction: 'long' | 'short'
  openTime: string
  closeTime: string
  openPrice: number
  closePrice: number
  volume: number
  pnl: number
  pnlPercent: number
  commission: number
}

export interface BacktestRunRequest {
  symbol: string
  contract: string
  period: string
  start: string
  end: string
  initial_capital: number
  risk_per_trade_pct: number
  max_margin_usage_pct: number
  slippage_ticks: number
  take_profit_r: number
  enable_take_profit: boolean
  strategy_params?: Record<string, unknown>
}

export interface BacktestSummary {
  initial_capital: number
  ending_equity: number
  total_return: number
  annual_return: number
  max_drawdown: number
  max_drawdown_amount: number
  win_rate: number
  profit_loss_ratio: number
  expectancy: number
  max_consecutive_losses: number
  total_commission: number
  total_slippage: number
  total_trades: number
  total_orders: number
  filled_orders: number
  rejected_orders: number
  contract_spec: Record<string, unknown>
}

export interface BacktestTrade {
  trade_no: string
  instrument_symbol: string
  contract_code: string
  direction: 'long' | 'short'
  open_time: string
  open_price: number
  close_time: string
  close_price: number
  volume: number
  turnover: number
  commission: number
  slippage: number
  gross_pnl: number
  net_pnl: number
  return_pct: number
  holding_bars: number
  entry_reason: string
  exit_reason: string
}

export interface BacktestOrder {
  order_id: string
  signal_time: string
  execution_time: string
  signal_index: number
  execution_index: number
  action: 'open' | 'add' | 'reduce' | 'exit'
  direction: 'long' | 'short'
  requested_volume: number | null
  status: 'pending' | 'filled' | 'rejected' | 'cancelled'
  reason: string
  stop_price?: number | null
  take_profit_price?: number | null
  forced_price?: number | null
  reject_reason?: string | null
}

export interface BacktestFill {
  fill_id: string
  order_id: string
  time: string
  action: 'open' | 'add' | 'reduce' | 'exit'
  direction: 'long' | 'short'
  volume: number
  price: number
  base_price: number
  commission: number
  slippage: number
  turnover: number
  margin: number
  reason: string
  stop_price?: number | null
  take_profit_price?: number | null
}

export interface BacktestEquityPoint {
  time: string
  equity: number
  cash: number
  floating_pnl: number
  margin_used: number
  position_volume: number
  close: number
}

export interface BacktestDrawdownPoint {
  time: string
  equity: number
  peak_equity: number
  drawdown: number
  drawdown_pct: number
}

export interface BacktestReportPayload {
  summary: BacktestSummary
  trades: BacktestTrade[]
  orders: BacktestOrder[]
  fills: BacktestFill[]
  equity_curve: BacktestEquityPoint[]
  drawdown_curve: BacktestDrawdownPoint[]
  warnings: string[]
  quality_status?: Record<string, unknown>
  profile_id?: string | null
  market_data_file_id?: number | null
  binding_snapshot?: Record<string, unknown> | null
}

export interface WatchlistInfo {
  code: string
  name: string
  category?: string | null
  description?: string | null
  item_count: number
}

export interface WatchlistItemInfo {
  symbol: string
  name?: string | null
  exchange_code?: string | null
  default_contract?: string | null
  available_periods: string[]
}

export interface BatchBacktestParameterTemplate {
  name: string
  label?: string | null
  strategy_params?: Record<string, unknown>
  overrides?: Record<string, unknown>
}

export interface BatchBacktestRunRequest {
  watchlist_code: string
  period: string
  start: string
  end: string
  symbols?: string[]
  initial_capital: number
  risk_per_trade_pct: number
  max_margin_usage_pct: number
  slippage_ticks: number
  take_profit_r: number
  enable_take_profit: boolean
  strategy_params?: Record<string, unknown>
  parameter_templates?: BatchBacktestParameterTemplate[]
}

export interface BatchBacktestTask {
  id: number
  task_no: string
  status: 'pending' | 'running' | 'completed' | 'failed' | 'cancelled' | 'partial_failed'
  progress: number
  total_items: number
  completed_items: number
  failed_items: number
  skipped_items: number
  error_message?: string | null
  created_at?: string | null
  started_at?: string | null
  finished_at?: string | null
  result_payload: {
    template_stats?: BatchTemplateStat[]
    top_symbols?: BatchTopSymbol[]
    [key: string]: unknown
  }
  profile_id?: string | null
  market_data_file_id?: number | null
  binding_snapshot?: Record<string, unknown> | null
}

export interface BatchBacktestReport {
  id: number
  task_no: string
  report_no: string
  template_name: string
  template_label?: string | null
  symbol: string
  contract: string
  period: string
  status: 'running' | 'completed' | 'failed' | 'skipped'
  suitability_label: '适合' | '观察' | '不适合' | '数据不足'
  suitability_score: number
  quality_status: Record<string, unknown>
  summary: BacktestSummary
  warnings: string[]
  error_message?: string | null
  created_at?: string | null
  started_at?: string | null
  finished_at?: string | null
}

export interface BatchTemplateStat {
  template_name: string
  count: number
  average_return: number
  median_max_drawdown: number
  average_score: number
  suitable_count: number
}

export interface BatchTopSymbol {
  symbol: string
  contract: string
  template_name: string
  suitability_label: string
  suitability_score: number
  total_return: number
  max_drawdown: number
  total_trades: number
}

export interface BacktestTaskEvent {
  id: number
  task_no: string
  status: BatchBacktestTask['status']
  progress: number
  total_items: number
  completed_items: number
  failed_items: number
  skipped_items: number
  error_message?: string | null
  result_payload?: BatchBacktestTask['result_payload']
}
