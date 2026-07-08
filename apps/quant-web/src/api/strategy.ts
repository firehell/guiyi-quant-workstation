import request from './request'
import { getStrategyRegistry } from './dashboard'
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

/** 获取策略 registry（只读） */
export function getStrategies() {
  return getStrategyRegistry().then((response) =>
    response.items.map((item) => ({
      id: item.strategy_code,
      name: item.name,
      type: (item.is_v1b ? 'trend' : 'pattern') as StrategyInfo['type'],
      status: 'running' as const,
      createdAt: '',
      updatedAt: '',
      description: item.description,
      params: {},
    })),
  )
}

/** 获取策略详情 */
export function getStrategyDetail(id: string) {
  return getStrategyRegistry().then((response) => {
    const item = response.items.find((entry) => entry.strategy_code === id)
    if (!item) throw new Error('strategy not found')
    return {
      id: item.strategy_code,
      name: item.name,
      type: (item.is_v1b ? 'trend' : 'pattern') as StrategyInfo['type'],
      status: 'running' as const,
      createdAt: '',
      updatedAt: '',
      description: item.description,
      params: {},
    }
  })
}

/** @deprecated 请使用 createBacktestTask */
export function createBacktest(data: {
  strategyId: string
  symbol: string
  startDate: string
  endDate: string
  params?: Record<string, unknown>
}) {
  return request.post<any, { backtestId: string }>('/api/backtests/tasks', {
    strategy_code: data.strategyId,
    symbol: data.symbol,
    start: data.startDate,
    end: data.endDate,
    strategy_params: data.params || {},
  })
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
