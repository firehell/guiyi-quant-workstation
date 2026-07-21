import assert from 'node:assert/strict'
import { describe, it } from 'node:test'

import { resolveEventSourceMode, resolveSignalSourceMode, sourceModeBadge } from '../src/utils/signalSourceMode.ts'

describe('signalSourceMode', () => {
  it('maps known source modes to capability badges', () => {
    const replay = sourceModeBadge('jm_v1b_historical_replay')
    assert.equal(replay.kind, 'historical-replay')
    assert.match(replay.label, /回放/)
  })

  it('derives jm_v1b_scan from watchlist when features missing', () => {
    assert.equal(
      resolveSignalSourceMode({ features: {}, watchlist_code: 'jm_v1b' }),
      'jm_v1b_scan',
    )
  })

  it('passes through event source_mode', () => {
    assert.equal(resolveEventSourceMode({ source_mode: 'live_confirmed' } as never), 'live_confirmed')
  })
})
