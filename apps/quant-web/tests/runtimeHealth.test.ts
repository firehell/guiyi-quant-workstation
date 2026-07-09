import assert from 'node:assert/strict'
import { describe, it } from 'node:test'

import { formatCountMap, formatLagSeconds, formatLatencyMs, readonlyFlagSummary, runtimeStatusType } from '../src/utils/runtimeHealth.ts'

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
})
