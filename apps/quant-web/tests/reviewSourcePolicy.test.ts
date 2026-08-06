import assert from 'node:assert/strict'
import { describe, it } from 'node:test'

import {
  filterSupportedReviewPage,
  filterSupportedReviewNotes,
  reviewResourcePaths,
  supportedReviewOrNull,
} from '../src/utils/reviewPresentation.ts'

function review(id: number, sourceType: string) {
  return {
    id,
    source_type: sourceType,
    mistake_tags: [],
    setup_tags: [],
    rule_tags: [],
    emotion_tags: [],
    screenshot_paths: [],
    ai_status: 'reserved',
    extra: {},
  }
}

describe('review source policy', () => {
  it('keeps only the explicit neutral source allowlist in review lists', () => {
    const rows = [
      review(1, 'strategy_signal'),
      review(2, 'signal_event'),
      review(3, 'signal_decision'),
      review(4, 'manual_trade'),
      review(5, 'backtest_trade'),
      review(6, 'unknown_source'),
    ]

    assert.deepEqual(
      filterSupportedReviewNotes(rows).map((row) => row.source_type),
      ['strategy_signal', 'signal_event', 'signal_decision', 'manual_trade'],
    )
  })

  it('preserves the backend-filtered paged total instead of replacing it with page length', () => {
    const page = filterSupportedReviewPage({
      items: [review(1, 'strategy_signal'), review(2, 'signal_event')],
      total: 120,
      limit: 100,
      offset: 0,
    })

    assert.equal(page.items.length, 2)
    assert.equal(page.total, 120)
  })

  it('fails closed for direct backtest and unknown review ids before bars can load', () => {
    assert.equal(supportedReviewOrNull(review(5, 'backtest_trade')), null)
    assert.equal(supportedReviewOrNull(review(6, 'unknown_source')), null)
    assert.equal(supportedReviewOrNull(review(4, 'manual_trade'))?.id, 4)
  })

  it('keeps save and attachment resource paths for strategy and manual reviews', () => {
    assert.deepEqual(reviewResourcePaths(review(1, 'strategy_signal')), {
      detail: '/api/reviews/1',
      bars: '/api/reviews/1/bars',
      attachments: '/api/reviews/1/attachments',
    })
    assert.deepEqual(reviewResourcePaths(review(4, 'manual_trade')), {
      detail: '/api/reviews/4',
      bars: '/api/reviews/4/bars',
      attachments: '/api/reviews/4/attachments',
    })
  })
})
