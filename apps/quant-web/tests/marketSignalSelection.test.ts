import test from 'node:test'
import assert from 'node:assert/strict'
import type { SignalEventRecord, StrategySignalRecord } from '../src/types/signal.ts'
import {
  eventMatchesSignalChart,
  selectSignalEventForChart,
  signalIdFromMarkerId,
  signalMarkerId,
} from '../src/utils/marketSignalSelection.ts'

const signal: StrategySignalRecord = {
  id: 3,
  strategy_id: 'jm_v1b',
  strategy_version_id: 'v1b.0',
  strategy_name: 'JM V1-B',
  strategy_version: 'v1b.0',
  symbol: 'jm',
  contract: 'JM2609',
  product: 'jm',
  continuous_contract: 'jm.MAIN',
  actual_contract: 'JM2609',
  interval: '15m',
  period: '15m',
  signal_time: '2026-07-03T14:30:00',
  status: 'new',
  strategy_status: 'entry_signal',
  direction: 'short',
  signal_type: 'entry',
  price: 1279.5,
  strength_score: 70,
  signal_level: 70,
  score_bucket: 70,
  bucket_label: '强信号',
  reason: 'fixture',
  current_price: 1279.5,
  open_volume: 1,
  margin_required: 0,
  risk_amount: 0,
  account_equity: 100000,
  reasons: [],
  data_role: 'primary',
  research_only: false,
  features: {},
  quality_status: { status: 'passed' },
  research_contract: false,
  alert_status: 'unread',
}

function event(overrides: Partial<SignalEventRecord>): SignalEventRecord {
  return {
    id: 1,
    event_key: 'event-1',
    event_type: 'signal_created',
    signal_id: signal.id,
    source_mode: 'historical_replay',
    strategy_name: signal.strategy_name,
    strategy_version: signal.strategy_version,
    symbol: 'jm',
    contract: 'JM2609',
    product: 'jm',
    continuous_contract: 'jm.MAIN',
    actual_contract: 'JM2609',
    period: '15m',
    direction: 'short',
    signal_status: 'entry_signal',
    lifecycle_status: 'new',
    score_bucket: 70,
    data_role: 'primary',
    quality_status: { status: 'passed' },
    payload: {},
    created_at: '2026-07-08T15:25:01',
    ...overrides,
  }
}

test('signal marker id round trips signal id', () => {
  assert.equal(signalMarkerId(signal), 'signal-3')
  assert.equal(signalIdFromMarkerId('signal-3'), 3)
  assert.equal(signalIdFromMarkerId('trade-T1-open'), null)
})

test('eventMatchesSignalChart checks current product contract and period', () => {
  assert.equal(eventMatchesSignalChart(event({}), signal, { product: 'jm', contract: 'JM2609', period: '15m' }), true)
  assert.equal(eventMatchesSignalChart(event({ actual_contract: 'JM2608' }), signal, { product: 'jm', contract: 'JM2609', period: '15m' }), false)
  assert.equal(eventMatchesSignalChart(event({ period: '5m' }), signal, { product: 'jm', contract: 'JM2609', period: '15m' }), false)
})

test('selectSignalEventForChart prefers latest matching created or changed event', () => {
  const stale = event({ id: 1, created_at: '2026-07-08T10:00:00' })
  const latestStatusOnly = event({ id: 2, event_type: 'signal_status_changed', created_at: '2026-07-08T16:00:00' })
  const latestMatching = event({ id: 3, event_type: 'signal_changed', created_at: '2026-07-08T15:00:00' })

  assert.equal(
    selectSignalEventForChart([stale, latestStatusOnly, latestMatching], signal, {
      product: 'jm',
      contract: 'JM2609',
      period: '15m',
    })?.id,
    3,
  )
})
