/** 交易信号 */
export interface SignalRecord {
  signalId: string
  strategyId: string
  strategyName: string
  symbol: string
  direction: 'long' | 'short' | 'close'
  price: number
  volume: number
  signalTime: string
  reason: string
  confidence: number
}
