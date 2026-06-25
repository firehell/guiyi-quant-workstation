import request from './request'
import type { ReviewNote, ReviewSourceTrade, ReviewStats, ReviewTag, ReviewUpdateRequest } from '@/types/review'

export function getReviewBacktestTrades(params: {
  symbol?: string
  period?: string
  report_id?: number
  reviewed?: boolean
} = {}) {
  return request.get<any, ReviewSourceTrade[]>('/api/reviews/sources/backtest-trades', { params })
}

export function createReviewFromBacktestTrade(tradeId: number) {
  return request.post<any, ReviewNote>(`/api/reviews/from-backtest-trade/${tradeId}`)
}

export function getReviews(params: {
  source_type?: string
  symbol?: string
  mistake_tag?: string
  market_phase?: string
  is_system_compliant?: boolean
} = {}) {
  return request.get<any, ReviewNote[]>('/api/reviews', { params })
}

export function getReview(reviewId: number) {
  return request.get<any, ReviewNote>(`/api/reviews/${reviewId}`)
}

export function updateReview(reviewId: number, data: ReviewUpdateRequest) {
  return request.put<any, ReviewNote>(`/api/reviews/${reviewId}`, data)
}

export function addReviewAttachment(reviewId: number, data: { file_path: string; file_type?: string; title?: string; meta?: Record<string, unknown> }) {
  return request.post<any, unknown>(`/api/reviews/${reviewId}/attachments`, data)
}

export function getReviewTags() {
  return request.get<any, ReviewTag[]>('/api/reviews/tags')
}

export function getReviewStats() {
  return request.get<any, ReviewStats>('/api/reviews/stats')
}
