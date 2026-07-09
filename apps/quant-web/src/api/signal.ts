import request from './request'
import type {
  SignalEventRecord,
  SignalLifecycleStatus,
  SignalRecord,
  SignalScanRequest,
  SignalScanTask,
  Stage9WechatNotification,
  Stage9WechatPreview,
  StrategySignalRecord,
} from '@/types/signal'

/** @deprecated 后端无 /api/signals 根路径，请使用 getLatestStrategySignals */
export function getSignals(params: {
  strategyId?: string
  symbol?: string
  startDate?: string
  endDate?: string
} = {}) {
  return getLatestStrategySignals({
    limit: 50,
    ...(params.symbol ? {} : {}),
  })
}

/** 获取最新信号（轮询降级方案） */
export function getLatestSignals(limit = 20) {
  return request.get<any, SignalRecord[]>('/api/signals/latest', { params: { limit } })
}

export function scanStrategySignals(data: SignalScanRequest) {
  return request.post<any, SignalScanTask>('/api/signals/scan', data)
}

export function scanJmV1bSignals(runInline = true) {
  return request.post<any, SignalScanTask>('/api/signals/v1b/jm/scan', null, { params: { run_inline: runInline } })
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
  product?: string
  continuous_contract?: string
  actual_contract?: string
  provider?: string
  source?: string
  data_role?: string
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

export function updateStrategySignalStatus(signalId: number, status: SignalLifecycleStatus) {
  return request.patch<any, StrategySignalRecord>(`/api/signals/${signalId}/status`, { status })
}

export function listSignalEvents(params: {
  signal_id?: number
  task_no?: string
  symbol?: string
  event_type?: string
  product?: string
  continuous_contract?: string
  actual_contract?: string
  limit?: number
} = {}) {
  return request.get<any, SignalEventRecord[]>('/api/signals/events', { params })
}

export function getSignalEvents(signalId: number, limit = 100) {
  return request.get<any, SignalEventRecord[]>(`/api/signals/${signalId}/events`, { params: { limit } })
}

export function getStage9WechatPreview(eventId: number) {
  return request.get<any, Stage9WechatPreview>(
    `/api/signals/events/${eventId}/stage9-wechat/preview`,
  )
}

export function getStage9WechatNotification(eventId: number) {
  return request.get<any, Stage9WechatNotification>(`/api/signals/events/${eventId}/stage9-wechat/notification`)
}

export function previewLiveEvaluator(params: {
  symbol?: string
  contract?: string
  entry_intervals?: string[]
  allow_warning_quality?: boolean
} = {}) {
  return request.post<any, import('@/types/signal').LiveSignalEvaluationResponse>(
    '/api/signals/live-evaluator/preview',
    {
      symbol: params.symbol || 'jm',
      contract: params.contract,
      entry_intervals: params.entry_intervals || ['15m', '5m'],
      allow_warning_quality: params.allow_warning_quality || false,
    },
  )
}
