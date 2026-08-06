import type { ReviewNote, ReviewSourceType } from '@/types/review'

type QueryValue = string | string[] | null | undefined

function positiveId(value: QueryValue): number | null {
  const selected = Array.isArray(value) ? value[0] : value
  const numeric = Number(selected)
  return Number.isInteger(numeric) && numeric > 0 ? numeric : null
}

const REVIEW_SOURCE_TYPES = new Set<ReviewSourceType>([
  'strategy_signal',
  'signal_event',
  'signal_decision',
  'manual_trade',
])

export type ReviewNotePayload = Omit<ReviewNote, 'source_type'> & { source_type: unknown }

export function isSupportedReviewSourceType(value: unknown): value is ReviewSourceType {
  return typeof value === 'string' && REVIEW_SOURCE_TYPES.has(value as ReviewSourceType)
}

export function supportedReviewOrNull(review: ReviewNotePayload): ReviewNote | null {
  if (!isSupportedReviewSourceType(review.source_type)) return null
  return { ...review, source_type: review.source_type }
}

export function filterSupportedReviewNotes(rows: ReviewNotePayload[]): ReviewNote[] {
  return rows.flatMap((row) => {
    const supported = supportedReviewOrNull(row)
    return supported ? [supported] : []
  })
}

export function filterSupportedReviewPage<T extends {
  items: ReviewNotePayload[]
  total: number
  limit: number
  offset: number
}>(page: T) {
  return { ...page, items: filterSupportedReviewNotes(page.items || []) }
}

export function reviewResourcePaths(review: Pick<ReviewNote, 'id'>) {
  const root = `/api/reviews/${review.id}`
  return {
    detail: root,
    bars: `${root}/bars`,
    attachments: `${root}/attachments`,
  }
}

export function parseReviewDeepLinkQuery(query: Record<string, QueryValue>) {
  return { review_id: positiveId(query.review_id) }
}

export function reviewSourceIdentity(review: Pick<ReviewNote, 'source_type' | 'source_id'>) {
  return review.source_id
    ? `${review.source_type} #${review.source_id}`
    : `${review.source_type} · source unavailable`
}
