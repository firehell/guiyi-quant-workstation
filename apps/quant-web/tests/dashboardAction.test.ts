import assert from 'node:assert/strict'
import { describe, it } from 'node:test'
import {
  buildDashboardActions,
  formatDashboardTimestamp,
} from '../src/utils/dashboardAction.ts'

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
    assert.deepEqual(actions.map((item) => item.kind), ['jm_15m'])
  })

  it('presents a new HTDY repainting event as observation rather than a live trading signal', () => {
    const action = buildDashboardActions({
      latestLiveSignalEvent: {
        event_id: 11,
        source_mode: 'live_realtime_repainting',
        lifecycle_status: 'new',
      },
      unfinishedReviewCount: 0,
    }).find((item) => item.kind === 'htdy_observation')

    assert.deepEqual(action, {
      kind: 'htdy_observation',
      title: '查看新的 HTDY 观察事件',
      detail: 'SignalEvent #11 为 first-seen 重绘观察；不是交易指令，不自动通知。',
      to: { name: 'signal', query: { tab: 'events', signal_event_id: '11' } },
    })
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

describe('dashboard time presentation', () => {
  it('formats explicit UTC timestamps in the workstation timezone', () => {
    assert.equal(formatDashboardTimestamp('2026-07-21T06:45:00Z'), '2026-07-21 14:45')
  })

  it('preserves timezone-free market timestamps without shifting them', () => {
    assert.equal(formatDashboardTimestamp('2026-07-21T14:45:00'), '2026-07-21 14:45')
  })

  it('uses a stable empty and invalid fallback', () => {
    assert.equal(formatDashboardTimestamp(null), '未提供')
    assert.equal(formatDashboardTimestamp('not-a-date'), 'not-a-date')
  })
})
