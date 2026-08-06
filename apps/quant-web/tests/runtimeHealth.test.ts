import assert from 'node:assert/strict'
import { describe, it } from 'node:test'

import {
  buildRuntimeRecoverySummary,
  formatCountMap,
  formatLagSeconds,
  formatLatencyMs,
  readonlyFlagSummary,
  runtimeStatusType,
} from '../src/utils/runtimeHealth.ts'

describe('runtimeHealth helpers', () => {
  it('maps runtime statuses to Naive UI tag types', () => {
    assert.equal(runtimeStatusType('ok'), 'success')
    assert.equal(runtimeStatusType('degraded'), 'warning')
    assert.equal(runtimeStatusType('failed'), 'error')
    assert.equal(runtimeStatusType('unknown'), 'default')
  })

  it('formats latency and lag values for dense dashboard display', () => {
    assert.equal(formatLatencyMs(1.234), '1.23 ms')
    assert.equal(formatLatencyMs(12.34), '12.3 ms')
    assert.equal(formatLagSeconds(null), '-')
    assert.equal(formatLagSeconds(45), '45s')
    assert.equal(formatLagSeconds(125), '2m 5s')
    assert.equal(formatLagSeconds(7200), '2h')
  })

  it('formats count maps in stable key order', () => {
    assert.equal(formatCountMap({ success: 2, failed: 1 }), 'failed: 1, success: 2')
    assert.equal(formatCountMap({}), '-')
  })

  it('builds readonly boundary summaries without implying actions', () => {
    const flags = readonlyFlagSummary({
      readonly: true,
      would_start_services: false,
      would_enqueue_jobs: false,
      would_send_notifications: false,
    })

    assert.deepEqual(
      flags.map((item) => `${item.label}=${String(item.value)}`),
      ['readonly=true', 'would_start_services=false', 'would_enqueue_jobs=false', 'would_send_notifications=false'],
    )
    assert.equal(flags.every((item) => item.value === item.expected), true)
  })

  it('summarizes heartbeat, watermark, last success, error, and bounded recovery facts', () => {
    const summary = buildRuntimeRecoverySummary({
      status: 'degraded',
      components: {
        scheduler: {
          status: 'degraded',
          heartbeat_at: '2026-07-25T15:01:00Z',
          heartbeat_age_seconds: 70,
        },
        after_market_scheduler: {
          status: 'degraded',
          next_retry_at: '2026-07-25T15:10:00Z',
          last_error_type: 'heartbeat_missing',
          scheduler_heartbeat: {
            heartbeat_at: '2026-07-25T15:02:00Z',
            heartbeat_age_seconds: 60,
          },
        },
        archive: {
          status: 'ok',
          latest_finished_at: '2026-07-25T15:00:00Z',
        },
        live_checkpoints: {
          status: 'ok',
          latest_success_at: '2026-07-25T14:59:00Z',
          recent_ingest: [{ last_bar_at: '2026-07-25T14:58:00Z' }],
          recent_aggregation: [{ last_bar_at: '2026-07-25T14:57:00Z' }],
        },
      },
    } as never)

    assert.equal(summary.heartbeatAge, '1m')
    assert.equal(summary.watermark, '2026-07-25T14:58:00Z')
    assert.equal(summary.lastSuccess, '2026-07-25T15:00:00Z')
    assert.equal(summary.error, 'heartbeat_missing')
    assert.match(summary.recovery, /有限重试/)
  })

  it('does not fall back to the retired runtime scheduler component', () => {
    const summary = buildRuntimeRecoverySummary({
      status: 'degraded',
      components: {
        scheduler: {
          status: 'ok',
          heartbeat_at: '2026-07-25T15:01:00Z',
          heartbeat_age_seconds: 70,
        },
        live_checkpoints: {
          recent_ingest: [],
          recent_aggregation: [],
        },
        rq: {},
        db: {},
        redis: {},
        notification_retry: {},
      },
    } as never)

    assert.equal(summary.heartbeat, null)
    assert.equal(summary.heartbeatAge, '-')
  })
})
