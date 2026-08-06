/** 策略中心只读信息。 */
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
