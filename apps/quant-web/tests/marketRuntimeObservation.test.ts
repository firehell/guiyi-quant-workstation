import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { describe, it } from 'node:test'
import { fileURLToPath } from 'node:url'

import {
  assertNoSensitivePayload,
  buildMarketRuntimeObservation,
  normalizeRuntimeHealthDisplay,
  observationFieldLabel,
} from '../src/utils/marketRuntimeObservation.ts'
import type { MarketRuntimeObservationInput } from '../src/types/marketRuntimeObservation.ts'

const fixtureDir = join(dirname(fileURLToPath(import.meta.url)), 'fixtures/marketRuntime')

function loadFixture(name: string): MarketRuntimeObservationInput & { fixture_id?: string; sensitive_probe?: unknown } {
  return JSON.parse(readFileSync(join(fixtureDir, name), 'utf8')) as MarketRuntimeObservationInput & {
    fixture_id?: string
    sensitive_probe?: unknown
  }
}

describe('marketRuntimeObservation', () => {
  it('builds ready_live fixture', () => {
    const ctx = buildMarketRuntimeObservation(loadFixture('ready_live.json'))
    assert.equal(ctx.data_mode.value, 'live')
    assert.equal(ctx.source_badge.value, 'live')
    assert.equal(ctx.actual_contract.value, 'JM2609')
    assert.equal(ctx.latest_live_1m.status, 'available')
    assert.equal(ctx.confirmed_count.value, 120)
    assert.equal(ctx.partial_count.value, 0)
    assert.equal(ctx.runtime_health_status.value, 'ok')
    assert.equal(ctx.active_data_version.status, 'unavailable')
    assert.equal(normalizeRuntimeHealthDisplay(ctx.runtime_health_status.value), 'ok')
  })

  it('builds blocked_target without inventing contract', () => {
    const ctx = buildMarketRuntimeObservation(loadFixture('blocked_target.json'))
    assert.equal(ctx.actual_contract.status, 'unavailable')
    assert.match(String(ctx.actual_contract.reason), /main_contract_map/)
    assert.equal(ctx.latest_live_1m.status, 'unavailable')
  })

  it('keeps degraded as not healthy', () => {
    const ctx = buildMarketRuntimeObservation(loadFixture('degraded_runtime.json'))
    assert.equal(ctx.runtime_health_status.value, 'degraded')
    assert.equal(ctx.runtime_health_status.status, 'warning')
    assert.notEqual(normalizeRuntimeHealthDisplay(ctx.runtime_health_status.value), 'ok')
    assert.match(observationFieldLabel(ctx.runtime_health_status), /not healthy/)
  })

  it('keeps confirmed and partial separate', () => {
    const ctx = buildMarketRuntimeObservation(loadFixture('stale_partial_live.json'))
    assert.equal(ctx.confirmed_count.value, 50)
    assert.equal(ctx.partial_count.value, 3)
    assert.equal(ctx.confirmed_count.status, 'available')
  })

  it('warns when chart merges partial into confirmed', () => {
    const ctx = buildMarketRuntimeObservation({
      data_mode: 'live',
      confirmed_count: 50,
      partial_count: 3,
      chart_row_count: 53,
    })
    assert.equal(ctx.confirmed_count.status, 'warning')
  })

  it('warns on historical/live silent mix', () => {
    const ctx = buildMarketRuntimeObservation({
      data_mode: 'live',
      conflicting_data_mode: 'historical',
    })
    assert.equal(ctx.data_mode.status, 'warning')
    assert.match(String(ctx.data_mode.reason), /must not silently mix/)
  })

  it('rejects sensitive path payloads', () => {
    const leaks = assertNoSensitivePayload({
      historical_coverage: { '15m': { file_path: '/tmp/secret.parquet' } },
    })
    assert.ok(leaks.some((item) => item.includes('file_path')))
    const clean = assertNoSensitivePayload(loadFixture('stale_partial_live.json'))
    assert.deepEqual(clean, [])
  })
})
