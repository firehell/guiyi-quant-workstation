import request from './request'
import type { StrategyInfo, BacktestResult } from '@/types/strategy'

/** 获取策略列表 */
export function getStrategies() {
  return request.get<any, StrategyInfo[]>('/api/strategies')
}

/** 获取策略详情 */
export function getStrategyDetail(id: string) {
  return request.get<any, StrategyInfo>(`/api/strategies/${id}`)
}

/** 创建回测任务 */
export function createBacktest(data: {
  strategyId: string
  symbol: string
  startDate: string
  endDate: string
  params?: Record<string, unknown>
}) {
  return request.post<any, { backtestId: string }>('/api/backtests', data)
}

/** 获取回测结果 */
export function getBacktestResult(id: string) {
  return request.get<any, BacktestResult>(`/api/backtests/${id}/result`)
}
