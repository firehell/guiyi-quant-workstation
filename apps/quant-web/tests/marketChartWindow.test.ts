import assert from 'node:assert/strict'
import { describe, it } from 'node:test'

import {
  continuousContractFor,
  defaultContractViewForPeriod,
  defaultDateRangeMs,
  isLivePeriodSupported,
  preferredOpenPeriod,
  resolveContractForView,
} from '../src/utils/marketChartWindow.ts'

describe('marketChartWindow', () => {
  it('resolves contract by view mode', () => {
    assert.equal(resolveContractForView('jm', 'JM2609', 'actual'), 'JM2609')
    assert.equal(resolveContractForView('jm', 'JM2609', 'continuous'), 'jm.MAIN')
    assert.equal(continuousContractFor('JM'), 'jm.MAIN')
  })

  it('defaults contract view by period', () => {
    assert.equal(defaultContractViewForPeriod('1d'), 'continuous')
    assert.equal(defaultContractViewForPeriod('1w'), 'continuous')
    assert.equal(defaultContractViewForPeriod('15m'), 'actual')
  })

  it('builds period-aware default date windows', () => {
    const end = Date.parse('2026-07-09T00:00:00')
    const start = Date.parse('2020-01-01T00:00:00')
    const day = 24 * 60 * 60 * 1000
    const [oneMinuteStart] = defaultDateRangeMs('1m', start, end)
    const [dailyStart] = defaultDateRangeMs('1d', start, end)
    assert.ok(end - oneMinuteStart <= 8 * day)
    assert.ok(end - dailyStart >= 365 * 3 * day - day)
    assert.ok(dailyStart > start)
  })

  it('prefers open period from coverage', () => {
    assert.equal(
      preferredOpenPeriod({
        '1d': { available: true },
        '1w': { available: true },
      }),
      '1d',
    )
    assert.equal(
      preferredOpenPeriod({
        '1m': { available: true },
      }),
      '1m',
    )
  })

  it('knows live supported periods', () => {
    assert.equal(isLivePeriodSupported('15m'), true)
    assert.equal(isLivePeriodSupported('1d'), false)
    assert.equal(isLivePeriodSupported('1w'), false)
  })
})
