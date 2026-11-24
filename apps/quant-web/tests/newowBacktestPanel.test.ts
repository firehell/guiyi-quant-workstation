import assert from 'node:assert/strict'
import test from 'node:test'
import { backtestSelection, createBacktestReader } from '../src/utils/newowBacktestReader.ts'
import type { LatestBacktest } from '../src/utils/newowBacktestReader.ts'

const trend = backtestSelection('FU', 'trend', '5m', false)!
const trial = backtestSelection('fu', 'trend', '5m', true)!
const result = (id: string): LatestBacktest => ({
  result: { run_id: id, as_of_trading_day: '2026-01-05', qualification: 'TRIAL', manifest: {}, summary: {} },
  last_attempt: null,
})

test('only the three V2 strategies use the six backtest frequencies', () => {
  assert.equal(backtestSelection('FU', 'main_rise', '5m', false), null)
  assert.equal(backtestSelection('FU', 'trend', '1m', false), null)
  assert.equal(backtestSelection('FU', 'dual_fusion', '1w', false)?.strategy, 'dual_fusion')
  assert.equal(trend.research_profile_id, 'trend_5m_rqalpha_v1')
  assert.equal(trial.research_profile_id, 'trend_5m_rqalpha_trial_v1')
})

test('a late summary cannot replace the selected series and pages stay pinned to a run', async () => {
  let finishOld!: (value: LatestBacktest) => void
  const calls: unknown[] = []
  const reader = createBacktestReader({
    latest: (key) => key === trend ? new Promise(resolve => { finishOld = resolve }) : Promise.resolve(result('B')),
    page: async (id, kind, cursor) => {
      calls.push([id, kind, cursor])
      return { run_id: id, items: [], next_cursor: cursor ? null : `${kind}-cursor` }
    },
  }, () => {})
  const old = reader.select(trend)
  await reader.select(trial)
  await reader.more('trades')
  finishOld(result('A'))
  await old
  assert.equal(reader.state.latest?.result?.run_id, 'B')
  assert.deepEqual(calls, [['B', 'trades', null], ['B', 'equity', null], ['B', 'trades', 'trades-cursor']])
})

test('empty and failed attempts retain the actual published cutoff', async () => {
  const failure = { run_id: 'new', generation: 2, status: 'FAILED' as const, error_code: 'RANK1_AS_KNOWN_UNPROVEN', as_of_trading_day: '2026-01-06' }
  let latest: LatestBacktest = { result: null, last_attempt: failure }
  const reader = createBacktestReader({
    latest: async () => latest,
    page: async (id) => ({ run_id: id, items: [], next_cursor: null }),
  }, () => {})
  await reader.select(trend)
  assert.equal(reader.state.latest?.result, null)
  latest = { ...result('old'), last_attempt: failure }
  await reader.select(trend)
  assert.equal(reader.state.latest?.result?.as_of_trading_day, '2026-01-05')
  assert.equal(reader.state.latest?.last_attempt?.error_code, 'RANK1_AS_KNOWN_UNPROVEN')
})
