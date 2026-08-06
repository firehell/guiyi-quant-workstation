import assert from 'node:assert/strict'
import { describe, it } from 'node:test'

import {
  toCanonicalBarsRequest,
  toCanonicalIndicatorsRequest,
} from '../src/utils/dataCoreV2Market.ts'

describe('dataCoreV2Market', () => {
  it('builds an explicit continuous canonical bars request without legacy selectors', () => {
    assert.deepEqual(
      toCanonicalBarsRequest({
        dataset_kind: 'continuous',
        symbol: 'jm',
        contract: 'jm.MAIN',
        period: '15m',
        start: '2026-07-01T01:00:00Z',
        end: '2026-07-02T01:00:00Z',
        profile_id: 'legacy-profile',
        expected_lineage_token: 'legacy-token',
        tail: true,
        limit: 10000,
      }),
      {
        dataset_kind: 'continuous',
        symbol: 'jm',
        contract_or_series: 'jm.MAIN',
        frequency: '15m',
        start: '2026-07-01T01:00:00Z',
        end: '2026-07-02T01:00:00Z',
      },
    )
  })

  it('builds an explicit actual-dominant canonical indicator request', () => {
    assert.deepEqual(
      toCanonicalIndicatorsRequest({
        dataset_kind: 'actual_dominant',
        symbol: 'jm',
        contract: 'JM2609',
        period: '1m',
        indicator_codes: 'ema10,ema21',
        display_start: '2026-07-01T01:00:00Z',
        display_end: '2026-07-01T02:00:00Z',
        display_bar_count: 60,
      }),
      {
        dataset_kind: 'actual_dominant',
        symbol: 'jm',
        contract_or_series: 'JM2609',
        frequency: '1m',
        start: '2026-07-01T01:00:00Z',
        end: '2026-07-01T02:00:00Z',
        indicator_codes: 'ema10,ema21',
        display_bar_count: 60,
      },
    )
  })

  it('fails closed when canonical bars have no exact window', () => {
    assert.throws(
      () => toCanonicalBarsRequest({
        dataset_kind: 'actual_dominant', symbol: 'jm', contract: 'JM2609', period: '1m',
      }),
      /exact_start_end_required/,
    )
  })

  it('fails closed on date-only canonical windows before calling FastAPI', () => {
    assert.throws(
      () => toCanonicalBarsRequest({
        dataset_kind: 'continuous', symbol: 'jm', contract: 'JM.MAIN', period: '1d',
        start: '2026-07-01', end: '2026-07-02',
      }),
      /start_rfc3339_timezone_required/,
    )
  })

  it('accepts a canonical request for any catalog product', () => {
    assert.deepEqual(
      toCanonicalBarsRequest({
        dataset_kind: 'actual_dominant', symbol: 'i', contract: 'I2609', period: '1m',
        start: '2026-07-01T01:00:00Z', end: '2026-07-01T02:00:00Z',
      }),
      {
        dataset_kind: 'actual_dominant', symbol: 'i', contract_or_series: 'I2609', frequency: '1m',
        start: '2026-07-01T01:00:00Z', end: '2026-07-01T02:00:00Z',
      },
    )
  })
})
