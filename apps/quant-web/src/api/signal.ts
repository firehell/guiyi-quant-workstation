import request from './request'
import type { SignalRecord, SignalScanRequest, SignalScanTask, StrategySignalRecord } from '@/types/signal'

/** 获取信号列表 */
export function getSignals(params: {
  strategyId?: string
  symbol?: string
  startDate?: string
  endDate?: string
}) {
  return request.get<any, SignalRecord[]>('/api/signals', { params })
}

/** 获取最新信号（轮询降级方案） */
export function getLatestSignals(limit = 20) {
  return request.get<any, SignalRecord[]>('/api/signals/latest', { params: { limit } })
}

export function scanStrategySignals(data: SignalScanRequest) {
  return request.post<any, SignalScanTask>('/api/signals/scan', data)
}

export function getSignalScanTask(taskNo: string) {
  return request.get<any, SignalScanTask>(`/api/signals/tasks/${taskNo}`)
}

export function getTaskStrategySignals(taskNo: string) {
  return request.get<any, StrategySignalRecord[]>(`/api/signals/tasks/${taskNo}/signals`)
}

export function getLatestStrategySignals(params: {
  watchlist_code?: string
  period?: string
  score_bucket?: number
  direction?: string
  status?: string
  limit?: number
} = {}) {
  return request.get<any, StrategySignalRecord[]>('/api/signals/latest', { params })
}

export function ackStrategySignal(signalId: number) {
  return request.post<any, StrategySignalRecord>(`/api/signals/${signalId}/ack`)
}
