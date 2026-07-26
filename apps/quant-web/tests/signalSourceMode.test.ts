import assert from 'node:assert/strict'
import { describe, it } from 'node:test'

import {
  resolveEventSourceMode,
  resolveSignalSourceMode,
  signalQualification,
  signalResearchIdentity,
  sourceModeBadge,
} from '../src/utils/signalSourceMode.ts'

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

  it('keeps the exact strategy and observation identity readable', () => {
    assert.deepEqual(
      signalResearchIdentity({
        strategy_code: 'su_bing_ema21',
        strategy_id: 'strategy-17',
        strategy_version_id: 'v1b.2',
        strategy_version: '1.2.0',
        source_mode: 'live_confirmed',
        features: {},
      }),
      {
        strategy: 'su_bing_ema21 · v1b.2',
        observation: 'live_confirmed',
      },
    )
  })

  it('qualifies research input without promoting it to a validated signal', () => {
    assert.deepEqual(
      signalQualification({
        data_role: 'primary',
        quality_status: { status: 'passed' },
        research_only: true,
      }),
      {
        status: 'passed',
        label: '研究输入合格',
        note: 'primary 数据质量已通过；信号仍仅供研究观察',
      },
    )
    assert.equal(
      signalQualification({
        data_role: 'primary',
        quality_status: { status: 'warning' },
        research_only: true,
      }).label,
      '研究输入需复核',
    )
  })
})
