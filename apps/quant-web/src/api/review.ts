import request from './request'
import type { ReviewBarsResponse, ReviewNote, ReviewSourceTrade, ReviewStats, ReviewTag, ReviewUpdateRequest } from '@/types/review'

/** 从回测成交拉取可复盘源交易列表 */
export function getReviewBacktestTrades(params: {
  symbol?: string
  period?: string
  report_id?: number
  reviewed?: boolean
} = {}) {
  return request.get<any, ReviewSourceTrade[]>('/api/reviews/sources/backtest-trades', { params })
}

/** 基于回测成交创建复盘笔记 */
export function createReviewFromBacktestTrade(tradeId: number, data?: Partial<ReviewUpdateRequest>) {
  return request.post<any, ReviewNote>(`/api/reviews/from-backtest-trade/${tradeId}`, data || {})
}

/** 用户显式确认后，基于 StrategySignal 创建或恢复复盘。 */
export function createReviewFromStrategySignal(signalId: number, data?: Partial<ReviewUpdateRequest>) {
  return request.post<any, ReviewNote>(`/api/reviews/from-strategy-signal/${signalId}`, data || {})
}

/** 用户显式确认后，基于 SignalEvent 创建或恢复复盘。 */
export function createReviewFromSignalEvent(eventId: number, data?: Partial<ReviewUpdateRequest>) {
  return request.post<any, ReviewNote>(`/api/reviews/from-signal-event/${eventId}`, data || {})
}

/** 按条件筛选复盘笔记列表 */
export function getReviews(params: {
  source_type?: string
  source_id?: number
  symbol?: string
  mistake_tag?: string
  market_phase?: string
  is_system_compliant?: boolean
} = {}) {
  return request.get<any, ReviewNote[]>('/api/reviews', { params })
}

/** 获取单条复盘详情 */
export function getReview(reviewId: number) {
  return request.get<any, ReviewNote>(`/api/reviews/${reviewId}`)
}

/** 获取复盘关联 K 线 bars（用于复盘图） */
export function getReviewBars(reviewId: number) {
  return request.get<any, ReviewBarsResponse>(`/api/reviews/${reviewId}/bars`)
}

/** 更新复盘笔记内容/标签 */
export function updateReview(reviewId: number, data: ReviewUpdateRequest) {
  return request.put<any, ReviewNote>(`/api/reviews/${reviewId}`, data)
}

/** 为复盘追加附件元数据（路径由服务端校验） */
export function addReviewAttachment(reviewId: number, data: { file_path: string; file_type?: string; title?: string; meta?: Record<string, unknown> }) {
  return request.post<any, unknown>(`/api/reviews/${reviewId}/attachments`, data)
}

/** 获取复盘可用标签字典 */
export function getReviewTags() {
  return request.get<any, ReviewTag[]>('/api/reviews/tags')
}

/** 获取复盘统计汇总 */
export function getReviewStats() {
  return request.get<any, ReviewStats>('/api/reviews/stats')
}
