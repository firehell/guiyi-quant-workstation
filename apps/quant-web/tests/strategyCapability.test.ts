import assert from 'node:assert/strict'
import { describe, it } from 'node:test'

import {
  groupRegistryByCapability,
  isRejectedStrategy,
  resolveStrategyCapabilityCategories,
} from '../src/utils/strategyCapability.ts'
import type { StrategyRegistryItem } from '../src/types/dashboard.ts'

const baseItem = (overrides: Partial<StrategyRegistryItem> = {}): StrategyRegistryItem => ({
  strategy_code: 'demo',
  name: 'Demo',
  description: 'demo',
  periods: [],
  is_v1b: false,
  spec_doc_exists: false,
  ...overrides,
})

describe('strategyCapability', () => {
  it('defaults to research_only without machine capability', () => {
    assert.deepEqual(resolveStrategyCapabilityCategories(baseItem()), ['research_only'])
  })

  it('filters the retired backtest capability while preserving non-backtest research', () => {
    const item = baseItem({
      capability_classes: ['formal_historical_backtest', 'historical_scan'],
    } as never)
    assert.deepEqual(resolveStrategyCapabilityCategories(item), ['historical_scan'])
  })

  it('marks rejected strategies and blocks live actions', () => {
    const item = baseItem({ validation_outcome: 'rejected', scan_endpoint: '/scan' })
    assert.deepEqual(resolveStrategyCapabilityCategories(item), ['rejected'])
    assert.equal(isRejectedStrategy(item), true)
  })

  it('does not treat is_v1b alone as validated capability', () => {
    const item = baseItem({ is_v1b: true })
    assert.deepEqual(resolveStrategyCapabilityCategories(item), ['research_only'])
  })

  it('groups registry items into capability sections', () => {
    const grouped = groupRegistryByCapability([
      baseItem({
        strategy_code: 'jm',
        capability_classes: ['historical_scan'],
      }),
      baseItem({ strategy_code: 'generic' }),
    ])
    assert.equal(grouped.historical_scan.length, 1)
    assert.equal(grouped.research_only.length, 1)
  })
})
