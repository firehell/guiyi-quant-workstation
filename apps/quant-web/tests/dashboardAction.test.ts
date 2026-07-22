import assert from 'node:assert/strict'
import { describe, it } from 'node:test'
import { buildDashboardActions } from '../src/utils/dashboardAction.ts'

describe('dashboard actions', () => {
  it('prioritizes explicit runtime failure before data, live event, review, and JM entry', () => {
    const actions = buildDashboardActions({
      runtimeStatus: 'failed',
      afterMarketStatus: 'failed',
      dataStatus: 'blocked',
      latestLiveSignalEvent: {
        event_id: 9,
        source_mode: 'live_confirmed',
        lifecycle_status: 'new',
      },
      unfinishedReviewCount: 2,
      latestReportId: 14,
    })
    assert.deepEqual(actions.map((item) => item.kind), [
      'runtime',
      'data',
      'live_signal',
      'review',
      'jm_15m',
    ])
  })

  it('does not promote unknown state or historical replay into a failure/live action', () => {
    const actions = buildDashboardActions({
      runtimeStatus: 'unknown',
      afterMarketStatus: 'unknown',
      dataStatus: 'unknown',
      latestLiveSignalEvent: {
        event_id: 10,
        source_mode: 'historical_replay',
        lifecycle_status: 'new',
      },
      unfinishedReviewCount: 0,
      latestReportId: 15,
    })
    assert.deepEqual(actions.map((item) => item.kind), ['report', 'jm_15m'])
  })

  it('always builds the canonical JM 15m historical actual quick entry', () => {
    const action = buildDashboardActions({ unfinishedReviewCount: 0 }).at(-1)
    assert.equal(action?.kind, 'jm_15m')
    assert.deepEqual(action?.to, {
      name: 'market-chart',
      query: {
        symbol: 'jm',
        period: '15m',
        contract_view: 'actual',
        data_mode: 'historical',
      },
    })
  })
})
