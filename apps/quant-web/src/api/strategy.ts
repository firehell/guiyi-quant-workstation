import request from './request'
import type {
  BacktestReportPayload,
  BacktestResult,
  BacktestRunRequest,
  BatchBacktestReport,
  BatchBacktestRunRequest,
  BatchBacktestTask,
  StrategyInfo,
  WatchlistInfo,
  WatchlistItemInfo,
} from '@/types/strategy'

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

/** 同步运行苏冰单品种回测 */
export function runBacktest(data: BacktestRunRequest) {
  return request.post<any, BacktestReportPayload>('/api/backtests/run', data)
}

export function getWatchlists() {
  return request.get<any, WatchlistInfo[]>('/api/watchlists')
}

export function getWatchlistItems(code: string) {
  return request.get<any, WatchlistItemInfo[]>(`/api/watchlists/${code}/items`)
}

export function runBatchBacktest(data: BatchBacktestRunRequest) {
  return request.post<any, BatchBacktestTask>('/api/backtests/run-batch', data)
}

export function getBacktestTask(taskNo: string) {
  return request.get<any, BatchBacktestTask>(`/api/backtests/tasks/${taskNo}`)
}

export function getBacktestTaskReports(taskNo: string) {
  return request.get<any, BatchBacktestReport[]>(`/api/backtests/tasks/${taskNo}/reports`)
}

export function getBacktestReport(reportId: number) {
  return request.get<any, BacktestReportPayload & BatchBacktestReport>(`/api/backtests/reports/${reportId}`)
}
