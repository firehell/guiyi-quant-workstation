import assert from 'node:assert/strict'
import { describe, it } from 'node:test'
import {
  MARKET_RIGHT_RAIL_TABS,
  resolveMarketRightRailTab,
} from '../src/utils/marketRightRail.ts'

describe('market right rail tab', () => {
  it('opens signal for explicit signal or event context', () => {
    assert.equal(resolveMarketRightRailTab({ preferred: 'strategy', hasSignalContext: true }), 'signal')
  })

  it('opens review for an explicit review context when signal context is absent', () => {
    assert.equal(resolveMarketRightRailTab({ preferred: 'strategy', hasReviewContext: true }), 'review')
  })

  it('keeps a valid manual preference when no deep-link context exists', () => {
    assert.equal(resolveMarketRightRailTab({ preferred: 'runtime' }), 'runtime')
    assert.equal(resolveMarketRightRailTab({ preferred: 'invalid' }), 'strategy')
  })

  it('displays the legacy strategy key as the neutral market facts tab', () => {
    assert.deepEqual(MARKET_RIGHT_RAIL_TABS[0], { name: 'strategy', label: '盘面' })
    assert.equal(resolveMarketRightRailTab({ preferred: 'strategy' }), 'strategy')
  })
})
