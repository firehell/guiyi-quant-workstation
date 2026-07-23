import assert from 'node:assert/strict'
import { describe, it } from 'node:test'
import { shouldRefreshRuntimePulse } from '../src/utils/runtimePulse.ts'
import { parseWorkspaceContext } from '../src/utils/workspaceContext.ts'

describe('workspace context', () => {
  it('reads only explicit URL context without inventing missing fields', () => {
    assert.deepEqual(
      parseWorkspaceContext({
        symbol: 'jm',
        contract: 'JM2609',
        period: '15m',
        data_mode: 'historical',
        contract_view: 'actual',
      }),
      {
        symbol: 'JM',
        contract: 'JM2609',
        period: '15m',
        mode: 'historical',
        contractView: 'actual',
      },
    )
    assert.deepEqual(parseWorkspaceContext({ report_id: '14' }), {})
  })

  it('uses the first explicit query value and ignores blanks', () => {
    assert.deepEqual(
      parseWorkspaceContext({ symbol: ['rb', 'jm'], period: '', data_mode: 'live' }),
      { symbol: 'RB', mode: 'live' },
    )
  })
})

describe('runtime pulse refresh policy', () => {
  it('refreshes only when visible, stale, and not already in flight', () => {
    assert.equal(
      shouldRefreshRuntimePulse({ visible: true, inFlight: false, now: 70_000, loadedAt: 0 }),
      true,
    )
    assert.equal(
      shouldRefreshRuntimePulse({ visible: false, inFlight: false, now: 70_000, loadedAt: 0 }),
      false,
    )
    assert.equal(
      shouldRefreshRuntimePulse({ visible: true, inFlight: true, now: 70_000, loadedAt: 0 }),
      false,
    )
    assert.equal(
      shouldRefreshRuntimePulse({ visible: true, inFlight: false, now: 50_000, loadedAt: 1_000 }),
      false,
    )
  })
})
