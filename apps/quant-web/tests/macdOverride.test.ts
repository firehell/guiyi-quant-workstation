import assert from 'node:assert/strict'
import { describe, it } from 'node:test'

import { macdOverrideToResult } from '../src/utils/macdOverride.ts'
import type { MarketMacdIndicatorResponse } from '../src/types/market.ts'

describe('macdOverrideToResult', () => {
  it('keeps only ready valid numeric MACD points', () => {
    const override = _override({
      dif: [
        { time: '2026-07-01T09:15:00', value: null, ready: false, valid: true },
        { time: '2026-07-01T09:30:00', value: 1.25, ready: true, valid: true },
        { time: '2026-07-01T09:45:00', value: 0, ready: true, valid: false, reason: 'input_invalid' },
      ],
      dea: [{ time: '2026-07-01T09:30:00', value: 1, ready: true, valid: true }],
      histogram: [{ time: '2026-07-01T09:30:00', value: 0.5, ready: true, valid: true }],
    })

    const result = macdOverrideToResult(override)

    assert.deepEqual(result?.dif, [{ time: '2026-07-01T09:30:00', value: 1.25 }])
    assert.deepEqual(result?.dea, [{ time: '2026-07-01T09:30:00', value: 1 }])
    assert.deepEqual(result?.histogram, [{ time: '2026-07-01T09:30:00', value: 0.5 }])
  })

  it('returns null when no backend override is available', () => {
    assert.equal(macdOverrideToResult(null), null)
  })
})

function _override(series: Pick<MarketMacdIndicatorResponse, 'dif' | 'dea' | 'histogram'>): MarketMacdIndicatorResponse {
  return {
    policy: 'web_macd_legacy_v1',
    indicator_code: 'macd',
    indicator_version: 'v1-draft',
    parameters: {},
    basis: {},
    source_bar_count: 3,
    ready_count: 1,
    request: {
      symbol: 'jm',
      contract: 'JM2609',
      period: '15m',
      limit: 10000,
    },
    ...series,
  }
}
