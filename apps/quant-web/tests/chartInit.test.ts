import assert from 'node:assert/strict'
import { describe, it } from 'node:test'

import {
  applyRouteSelectionFromQuery,
  deriveBarsRequestParams,
  resolveRouteAccessMode,
  resolveRoutePeriod,
  scopedCoverageParams,
} from '../src/utils/marketChartInit.ts'

describe('marketChartInit', () => {
  it('derives chart selection from route query without coverage', () => {
    const selection = applyRouteSelectionFromQuery({
      symbol: 'jm',
      contract: 'JM2609',
      period: '15m',
    })
    assert.deepEqual(selection, {
      selectedSymbol: 'jm',
      selectedActualContract: 'JM2609',
      selectedPeriod: '15m',
      contractView: 'actual',
    })
  })

  it('builds bars request params even when coverage is unavailable', () => {
    const selection = applyRouteSelectionFromQuery({
      symbol: 'jm',
      contract: 'JM2609',
      period: '15m',
    })
    assert.ok(selection)
    assert.deepEqual(deriveBarsRequestParams(selection), {
      symbol: 'jm',
      contract: 'JM2609',
      period: '15m',
    })
  })

  it('prefers interval when period is missing', () => {
    assert.equal(resolveRoutePeriod({ interval: '5m' }), '5m')
  })

  it('builds scoped coverage params from route query', () => {
    assert.deepEqual(
      scopedCoverageParams({
        symbol: 'jm',
        contract: 'JM2609',
        period: '15m',
        access_mode: 'research',
        profile_id: 'intraday_research_v1',
      }),
      {
        symbol: 'jm',
        contract: 'JM2609',
        period: '15m',
        profile_id: 'intraday_research_v1',
        access_mode: 'research',
        include_paths: false,
      },
    )
  })

  it('preserves symbol-only browser coverage when a deep link has no complete contract scope', () => {
    assert.deepEqual(scopedCoverageParams({ symbol: 'jm' }), {
      symbol: 'jm',
      profile_id: undefined,
      access_mode: 'browser',
      include_paths: false,
    })
  })

  it('preserves broad browser coverage even when the route has a selected contract and period', () => {
    assert.deepEqual(
      scopedCoverageParams({
        symbol: 'jm',
        contract: 'JM2609',
        period: '15m',
        access_mode: 'browser',
      }),
      {
        symbol: 'jm',
        profile_id: undefined,
        access_mode: 'browser',
        include_paths: false,
      },
    )
  })

  it('scopes a continuous daily research route to the continuous contract', () => {
    assert.deepEqual(
      scopedCoverageParams({
        symbol: 'jm',
        contract: 'JM2609',
        period: '1d',
        contract_view: 'continuous',
        access_mode: 'research',
        profile_id: 'long_horizon_daily_v1',
      }),
      {
        symbol: 'jm',
        contract: 'jm.MAIN',
        period: '1d',
        profile_id: 'long_horizon_daily_v1',
        access_mode: 'research',
        include_paths: false,
      },
    )
  })

  it('keeps browser as the safe route default and accepts explicit research', () => {
    assert.equal(resolveRouteAccessMode({}), 'browser')
    assert.equal(resolveRouteAccessMode({ access_mode: 'research' }), 'research')
    assert.equal(resolveRouteAccessMode({ access_mode: 'invalid' }), 'browser')
  })
})
