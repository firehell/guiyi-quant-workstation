import assert from 'node:assert/strict'
import { describe, it } from 'node:test'

import {
  buildChartResearchQuery,
  buildCreatedReviewRouteQuery,
  buildReviewResearchQuery,
  buildSignalEventReviewQuery,
  parseResearchContext,
  safeReturnRoute,
} from '../src/utils/researchNavigation.ts'

describe('researchNavigation', () => {
  it('ignores retired report/trade context and rejects a backtest return route', () => {
    const chart = buildChartResearchQuery({
      reportId: 14,
      tradeId: 3199,
      symbol: 'jm',
      contract: 'JM2609',
      period: '15m',
      returnRoute: '/backtest?report_id=14',
    })
    assert.deepEqual(chart, {
      symbol: 'jm',
      contract: 'JM2609',
      period: '15m',
    })
    assert.deepEqual(buildReviewResearchQuery(parseResearchContext(chart)), {})
    assert.equal(safeReturnRoute('/backtest?report_id=14'), null)
  })

  it('keeps signal event context separate from historical report context', () => {
    const query = buildChartResearchQuery({
      signalId: 6,
      signalEventId: 7,
      symbol: 'jm',
      contract: 'JM2609',
      period: '15m',
      dataMode: 'live',
      returnRoute: '/signal?tab=events&event_id=7',
    })
    assert.equal(query.signal_id, '6')
    assert.equal(query.signal_event_id, '7')
    assert.equal(query.data_mode, 'live')
    assert.equal(query.report_id, undefined)
    assert.deepEqual(buildReviewResearchQuery(parseResearchContext(query)), {
      source_type: 'signal_event',
      source_id: '7',
      signal_id: '6',
      signal_event_id: '7',
      return_route: '/signal?tab=events&event_id=7',
    })
    assert.deepEqual(buildSignalEventReviewQuery(7, 6, '/signal?tab=events&event_id=7'), {
      source_type: 'signal_event',
      source_id: '7',
      signal_id: '6',
      signal_event_id: '7',
      return_route: '/signal?tab=events&event_id=7',
    })
  })

  it('rejects external and malformed return routes', () => {
    assert.equal(safeReturnRoute('https://evil.example/path'), null)
    assert.equal(safeReturnRoute('//evil.example/path'), null)
    assert.equal(safeReturnRoute('/signal?tab=events'), '/signal?tab=events')
  })

  it('preserves safe signal context and return route after creating a review', () => {
    assert.deepEqual(buildCreatedReviewRouteQuery(21, {
      sourceType: 'signal_event',
      sourceId: 7,
      signalId: 6,
      signalEventId: 7,
      returnRoute: '/signal?tab=events&event_id=7',
    }), {
      review_id: '21',
      source_type: 'signal_event',
      source_id: '7',
      signal_id: '6',
      signal_event_id: '7',
      return_route: '/signal?tab=events&event_id=7',
    })
  })

  it('round-trips a manual review through Market with its exact safe return route', () => {
    const returnRoute = '/review?review_id=44'
    const chart = buildChartResearchQuery({
      reviewId: 44,
      symbol: 'jm',
      contract: 'JM2609',
      period: '15m',
      returnRoute,
    })
    assert.equal(chart.review_id, '44')
    assert.equal(chart.return_route, returnRoute)
    assert.deepEqual(buildReviewResearchQuery(parseResearchContext(chart)), {
      review_id: '44',
      return_route: returnRoute,
    })
  })
})
