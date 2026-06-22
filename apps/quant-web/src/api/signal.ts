import request from './request'
import type { SignalRecord } from '@/types/signal'

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
