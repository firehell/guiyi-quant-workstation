import type { ReviewNote } from '@/types/review'

type QueryValue = string | string[] | null | undefined

function positiveId(value: QueryValue): number | null {
  const selected = Array.isArray(value) ? value[0] : value
  const numeric = Number(selected)
  return Number.isInteger(numeric) && numeric > 0 ? numeric : null
}

export function parseReviewDeepLinkQuery(query: Record<string, QueryValue>) {
  return { review_id: positiveId(query.review_id) }
}

export function reviewSourceIdentity(review: Pick<ReviewNote, 'source_type' | 'source_id'>) {
  return review.source_id
    ? `${review.source_type} #${review.source_id}`
    : `${review.source_type} · source unavailable`
}
