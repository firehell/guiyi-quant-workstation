import request from './request'
import type { ReviewBarsResponse, ReviewNote, ReviewStats, ReviewTag, ReviewUpdateRequest } from '@/types/review'
import type { ReviewSourceType } from '@/types/review'
import type { PagedResponse } from '@/types/pagination'
import {
  filterSupportedReviewNotes,
  reviewResourcePaths,
  supportedReviewOrNull,
  type ReviewNotePayload,
} from '@/utils/reviewPresentation'

function requireSupportedReview(review: ReviewNotePayload): ReviewNote {
  const supported = supportedReviewOrNull(review)
  if (!supported) throw new Error('UNSUPPORTED_REVIEW_SOURCE')
  return supported
}

/** 用户显式确认后，基于 StrategySignal 创建或恢复复盘。 */
export async function createReviewFromStrategySignal(signalId: number, data?: Partial<ReviewUpdateRequest>) {
  const review = await request.post<any, ReviewNotePayload>(`/api/reviews/from-strategy-signal/${signalId}`, data || {})
  return requireSupportedReview(review)
}

/** 用户显式确认后，基于 SignalEvent 创建或恢复复盘。 */
export async function createReviewFromSignalEvent(eventId: number, data?: Partial<ReviewUpdateRequest>) {
  const review = await request.post<any, ReviewNotePayload>(`/api/reviews/from-signal-event/${eventId}`, data || {})
  return requireSupportedReview(review)
}

/** 按条件筛选复盘笔记列表 */
export async function getReviews(params: {
  source_type?: ReviewSourceType
  source_id?: number
  symbol?: string
  mistake_tag?: string
  market_phase?: string
  is_system_compliant?: boolean
  limit?: number
  offset?: number
} = {}) {
  const response = await request.get<any, PagedResponse<ReviewNotePayload>>('/api/reviews', { params: { paged: true, ...params } })
  const items = filterSupportedReviewNotes(response.items || [])
  return { ...response, items, total: items.length }
}

/** 获取单条复盘详情 */
export async function getReview(reviewId: number) {
  const review = await request.get<any, ReviewNotePayload>(reviewResourcePaths({ id: reviewId }).detail)
  return requireSupportedReview(review)
}

/** 获取复盘关联 K 线 bars（用于复盘图） */
export function getReviewBars(reviewId: number) {
  return request.get<any, ReviewBarsResponse>(reviewResourcePaths({ id: reviewId }).bars)
}

/** 更新复盘笔记内容/标签 */
export async function updateReview(reviewId: number, data: ReviewUpdateRequest) {
  const review = await request.put<any, ReviewNotePayload>(reviewResourcePaths({ id: reviewId }).detail, data)
  return requireSupportedReview(review)
}

/** 为复盘追加附件元数据（路径由服务端校验） */
export function addReviewAttachment(reviewId: number, data: { file_path: string; file_type?: string; title?: string; meta?: Record<string, unknown> }) {
  return request.post<any, unknown>(reviewResourcePaths({ id: reviewId }).attachments, data)
}

/** 获取复盘可用标签字典 */
export function getReviewTags() {
  return request.get<any, ReviewTag[]>('/api/reviews/tags')
}

/** 获取复盘统计汇总 */
export function getReviewStats() {
  return request.get<any, ReviewStats>('/api/reviews/stats')
}
