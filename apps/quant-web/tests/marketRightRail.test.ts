import assert from 'node:assert/strict'
import { describe, it } from 'node:test'
import { resolveMarketRightRailTab } from '../src/utils/marketRightRail.ts'

describe('market right rail tab', () => {
  it('opens signal for explicit signal or event context', () => {
    assert.equal(resolveMarketRightRailTab({ preferred: 'strategy', hasSignalContext: true }), 'signal')
  })

  it('opens review for report or trade context when signal context is absent', () => {
    assert.equal(resolveMarketRightRailTab({ preferred: 'strategy', hasReviewContext: true }), 'review')
  })

  it('keeps a valid manual preference when no deep-link context exists', () => {
    assert.equal(resolveMarketRightRailTab({ preferred: 'runtime' }), 'runtime')
    assert.equal(resolveMarketRightRailTab({ preferred: 'invalid' }), 'strategy')
  })
})
