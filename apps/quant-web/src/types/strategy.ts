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
