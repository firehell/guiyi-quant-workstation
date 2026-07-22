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

/** 触发策略信号扫描任务 */
export function scanStrategySignals(data: SignalScanRequest) {
  return request.post<any, SignalScanTask>('/api/signals/scan', data)
}

/** 触发 JM V1-B 专用信号扫描 */
export function scanJmV1bSignals(runInline = true) {
  return request.post<any, SignalScanTask>('/api/signals/v1b/jm/scan', null, { params: { run_inline: runInline } })
}

/** 查询信号扫描任务状态 */
export function getSignalScanTask(taskNo: string) {
  return request.get<any, SignalScanTask>(`/api/signals/tasks/${taskNo}`)
}

/** 获取扫描任务产出的策略信号列表 */
export function getTaskStrategySignals(taskNo: string) {
  return request.get<any, StrategySignalRecord[]>(`/api/signals/tasks/${taskNo}/signals`)
}

/** 按筛选条件获取最新策略信号 */
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

/** 确认（ACK）策略信号 */
export function ackStrategySignal(signalId: number) {
  return request.post<any, StrategySignalRecord>(`/api/signals/${signalId}/ack`)
}

/** 更新策略信号生命周期状态 */
export function updateStrategySignalStatus(signalId: number, status: SignalLifecycleStatus) {
  return request.patch<any, StrategySignalRecord>(`/api/signals/${signalId}/status`, { status })
}

/** 按条件列出信号事件流水 */
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

/** 按 event ID 精确恢复信号事件上下文 */
export function getSignalEvent(eventId: number) {
  return request.get<any, SignalEventRecord>(`/api/signals/events/${eventId}`)
}

/** 获取指定信号的事件流水 */
export function getSignalEvents(signalId: number, limit = 100) {
  return request.get<any, SignalEventRecord[]>(`/api/signals/${signalId}/events`, { params: { limit } })
}

/** 预览 Stage9 企业微信推送内容 */
export function getStage9WechatPreview(eventId: number) {
  return request.get<any, Stage9WechatPreview>(
    `/api/signals/events/${eventId}/stage9-wechat/preview`,
  )
}

/** 查询 Stage9 企业微信推送记录 */
export function getStage9WechatNotification(eventId: number) {
  return request.get<any, Stage9WechatNotification>(`/api/signals/events/${eventId}/stage9-wechat/notification`)
}

/** 预览实盘信号评估器输出（不落库） */
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
