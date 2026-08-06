import assert from 'node:assert/strict'
import { describe, it } from 'node:test'

import { parseReviewDeepLinkQuery } from '../src/utils/reviewPresentation.ts'

describe('reviewDeepLink', () => {
  it('parses only review_id and ignores retired trade/report ids', () => {
    assert.deepEqual(
      parseReviewDeepLinkQuery({
        review_id: '12',
        trade_id: '34',
        report_id: '56',
      }),
      { review_id: 12 },
    )
  })

  it('returns null for missing or invalid ids without inventing', () => {
    assert.deepEqual(parseReviewDeepLinkQuery({}), { review_id: null })
    assert.deepEqual(
      parseReviewDeepLinkQuery({
        review_id: '0',
        trade_id: '-1',
        report_id: 'abc',
      }),
      { review_id: null },
    )
  })

  it('uses first value when query param is an array', () => {
    assert.deepEqual(
      parseReviewDeepLinkQuery({
        review_id: ['7', '8'],
        trade_id: ['9'],
      }),
      { review_id: 7 },
    )
  })
})
