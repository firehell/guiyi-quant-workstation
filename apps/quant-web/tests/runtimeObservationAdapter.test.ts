import assert from 'node:assert/strict'
import { describe, it } from 'node:test'

import { buildMarketRuntimeObservation } from '../src/utils/marketRuntimeObservation.ts'
import {
  buildRuntimeHealthObservationInput,
  parseArchivedTradingDay,
} from '../src/utils/runtimeObservationAdapter.ts'
import type { RuntimeHealth } from '../src/types/runtime.ts'

function baseHealth(overrides: Partial<RuntimeHealth> = {}): RuntimeHealth {
  return {
    status: 'ok',
    generated_at: '2026-07-20T12:00:00+00:00',
    readonly: true,
    would_start_services: false,
    would_enqueue_jobs: false,
    would_send_notifications: false,
    components: {
      db: { status: 'ok', latency_ms: 1.2 },
      redis: { status: 'ok', latency_ms: 0.8 },
      rq: { status: 'ok', queues: [], worker_count: 1, workers: [] },
      live_checkpoints: {
        status: 'disabled',
        enabled: false,
        stale: false,
        ingest_count: 0,
        aggregation_count: 0,
        status_counts: {},
        recent_ingest: [],
        recent_aggregation: [],
      },
      notification_retry: {
        status: 'disabled',
        enabled: false,
        channel: 'enterprise_wechat',
        total_count: 0,
        retry_pending_count: 0,
        due_retry_count: 0,
        failed_count: 0,
        sent_count: 0,
        skipped_count: 0,
        pending_count: 0,
        last_error_type_counts: {},
      },
      archive: {
        status: 'disabled',
        enabled: false,
        latest_task_no: null,
      },
    },
    ...overrides,
  }
}

describe('runtimeObservationAdapter', () => {
  it('parses trading day from standard archive task_no', () => {
    assert.equal(
      parseArchivedTradingDay({ latest_task_no: 'archive:jm:JM2609:2026-07-08' }),
      '2026-07-08',
    )
  })

  it('does not treat raw task_no as archived_trading_day', () => {
    assert.equal(parseArchivedTradingDay({ latest_task_no: 'archive:jm:JM2609:2026-07-08' }), '2026-07-08')
    assert.equal(parseArchivedTradingDay({ latest_task_no: 'not-an-archive-task' }), null)
    assert.equal(parseArchivedTradingDay({ latest_task_no: 'archive:jm:JM2609' }), null)
    assert.equal(parseArchivedTradingDay({ latest_task_no: null }), null)
  })

  it('maps runtime health without inventing archived day from task_no', () => {
    const health = baseHealth()
    health.components.archive = {
      status: 'ok',
      enabled: true,
      latest_task_no: 'archive:jm:JM2609:2026-07-08',
      latest_task_status: 'success',
    }

    const input = buildRuntimeHealthObservationInput(health)
    assert.equal(input.archived_trading_day, '2026-07-08')
    assert.notEqual(input.archived_trading_day, health.components.archive.latest_task_no)

    const ctx = buildMarketRuntimeObservation(input)
    assert.equal(ctx.archived_trading_day.status, 'available')
    assert.equal(ctx.archived_trading_day.value, '2026-07-08')
  })

  it('marks archived day unavailable when task_no cannot be parsed', () => {
    const health = baseHealth()
    health.components.archive = {
      status: 'degraded',
      enabled: true,
      latest_task_no: 'archive:weird-format',
    }

    const input = buildRuntimeHealthObservationInput(health)
    assert.equal(input.archived_trading_day, null)
    assert.notEqual(input.archived_trading_day, 'archive:weird-format')

    const ctx = buildMarketRuntimeObservation(input)
    assert.equal(ctx.archived_trading_day.status, 'unavailable')
  })

  it('keeps degraded runtime health as not healthy', () => {
    const health = baseHealth({ status: 'degraded' })
    health.components.live_checkpoints = {
      status: 'degraded',
      enabled: true,
      stale: true,
      ingest_count: 1,
      aggregation_count: 0,
      status_counts: { failed: 1 },
      recent_ingest: [
        {
          id: 1,
          provider: 'rqdata',
          instrument_symbol: 'jm',
          contract_code: 'JM2609',
          period: '1m',
          source_mode: 'poll',
          status: 'failed',
          lag_seconds: 90,
          consecutive_error_count: 2,
        },
      ],
      recent_aggregation: [],
    }

    const input = buildRuntimeHealthObservationInput(health)
    assert.equal(input.runtime_health_status, 'degraded')
    assert.equal(input.checkpoint_status, 'degraded')
    assert.equal(input.checkpoint_lag_seconds, 90)

    const ctx = buildMarketRuntimeObservation(input)
    assert.equal(ctx.runtime_health_status.value, 'degraded')
    assert.equal(ctx.runtime_health_status.status, 'warning')
    assert.notEqual(ctx.runtime_health_status.value, 'ok')
  })
})
