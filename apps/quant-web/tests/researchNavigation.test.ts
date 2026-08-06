import assert from 'node:assert/strict'
import { describe, it } from 'node:test'

import {
  buildChartResearchQuery,
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
})
