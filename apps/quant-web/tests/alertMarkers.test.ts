import assert from 'node:assert/strict'
import { it } from 'node:test'

import { useSubingStrategyCurrent } from '../src/composables/useSubingStrategyCurrent.ts'
import type {
  AlertEvent,
  SubingStrategyAction,
  SubingStrategyActionPayloadWire,
  SubingStrategyCurrentResponse,
} from '../src/types/market.ts'
import {
  STRATEGY_ACTION_FACT_MISMATCH,
  reconcileSubingStrategyActions,
} from '../src/utils/subingStrategyReconciliation.ts'


it('dedupes one live event and one historical action by action_id', () => {
  const action = historicalAction()
  const event = liveEvent(action)
  event.strategy_action = {
    schema_version: 1,
    strategy_id: event.strategy_action!.strategy_id,
    formula_version: event.strategy_action!.formula_version,
    action_id: event.strategy_action!.action_id,
    episode_id: event.strategy_action!.episode_id,
    kind: event.strategy_action!.kind,
    symbol: event.strategy_action!.symbol,
    contract: event.strategy_action!.contract,
    trading_day: event.strategy_action!.trading_day,
    segment_start_trading_day: event.strategy_action!.segment_start_trading_day,
    opportunity_id: event.strategy_action!.opportunity_id,
    decision_at: '2026-08-14T13:15:00+00:00',
    effective_open_at: '2026-08-14T13:15:00+00:00',
    effective_bar_end: '2026-08-14T13:30:00+00:00',
    reference_price: event.strategy_action!.reference_price,
    fill_basis: event.strategy_action!.fill_basis,
    confirmation_source: event.strategy_action!.confirmation_source,
    reason_codes: event.strategy_action!.reason_codes,
    direction_context_source_day: event.strategy_action!.direction_context_source_day,
    direction_context_target_day: event.strategy_action!.direction_context_target_day,
    bound_reference_pivot: event.strategy_action!.bound_reference_pivot,
    entry: null,
    holding_bar_count: null,
    reference_change_percent: null,
  }
  const result = reconcileSubingStrategyActions([action], [], [event])

  assert.equal(result.markers.length, 1)
  assert.equal(result.markers[0].id, `historical:${action.action_id}`)
  assert.equal(result.markers[0].time, action.effective_bar_end)
  assert.deepEqual(result.errorCodes, [])
})


it('uses canonical marker and reports mismatch for conflicting same-id facts', () => {
  const action = historicalAction()
  const event = liveEvent(action)
  event.strategy_action = { ...event.strategy_action!, reference_price: '101' }

  const result = reconcileSubingStrategyActions([action], [], [event])

  assert.equal(result.markers.length, 1)
  assert.equal(result.markers[0].id, `historical:${action.action_id}`)
  assert.deepEqual(result.mismatchActionIds, [action.action_id])
  assert.deepEqual(result.errorCodes, [STRATEGY_ACTION_FACT_MISMATCH])
})


it('does not collapse a higher-precision live Decimal into an equal historical number', () => {
  const action = historicalAction()
  const event = liveEvent(action)
  event.strategy_action = { ...event.strategy_action!, reference_price: '100.0000000000000001' }

  const result = reconcileSubingStrategyActions([action], [], [event])

  assert.deepEqual(result.mismatchActionIds, [action.action_id])
})


it('renders a live-only strategy event at effective_bar_end', () => {
  const action = historicalAction()
  const result = reconcileSubingStrategyActions([], [], [liveEvent(action)])

  assert.deepEqual(result.markers.map((marker) => [marker.id, marker.time, marker.label]), [
    [`strategy-event:${action.action_id}`, action.effective_bar_end, '建多'],
  ])
})


it('keeps only the latest matching current request and exposes its open episode', async () => {
  const resolvers: Array<(value: SubingStrategyCurrentResponse) => void> = []
  const controller = useSubingStrategyCurrent({
    fetchCurrent: () => new Promise((resolve) => resolvers.push(resolve)),
  })
  const first = controller.refresh(identity('JM2609'))
  const second = controller.refresh(identity('JM2610'))
  resolvers[1](currentResponse('JM2610'))
  await second
  resolvers[0](currentResponse('JM2609'))
  await first

  assert.equal(controller.current.value?.contract, 'JM2610')
  assert.equal(controller.current.value?.position_state, 'long')
  assert.equal(controller.current.value?.current_episode?.state, 'open')
  controller.dispose()
})


function historicalAction(): SubingStrategyAction {
  return {
    action_id: 'subing-action:test',
    episode_id: 'subing-episode:test',
    strategy_id: 'subing_strategy_v1',
    formula_version: 'subing_strategy_15m_v1',
    kind: 'open_long',
    symbol: 'jm',
    contract: 'JM2609',
    trading_day: '2026-08-15',
    segment_start_trading_day: '2026-08-01',
    opportunity_id: 'subing-opportunity:test',
    decision_at: '2026-08-14T13:15:00Z',
    effective_open_at: '2026-08-14T13:15:00Z',
    effective_bar_end: '2026-08-14T13:30:00Z',
    reference_price: 100,
    fill_basis: 'next_bar_open',
    confirmation_source: 'formal_v1',
    reason_codes: [],
    direction_context_source_day: '2026-08-14',
    direction_context_target_day: '2026-08-15',
    bound_reference_pivot: null,
  }
}


function actionPayload(action: SubingStrategyAction): SubingStrategyActionPayloadWire {
  return {
    schema_version: 1,
    ...action,
    reference_price: String(action.reference_price),
    bound_reference_pivot: null,
    entry: null,
    holding_bar_count: null,
    reference_change_percent: null,
  }
}


function liveEvent(action: SubingStrategyAction): AlertEvent {
  return {
    id: 1,
    rule_code: 'subing_strategy_v1',
    symbol: action.symbol,
    contract: action.contract,
    trading_day: action.trading_day,
    frequency: '15m',
    bar_end: action.decision_at,
    result_codes: [action.kind],
    action_id: action.action_id,
    strategy_action: actionPayload(action),
    detected_at: action.decision_at,
    notification_attempted_at: action.decision_at,
  }
}


function identity(contract: string) {
  return {
    seriesKind: 'actual_dominant' as const,
    symbol: 'jm',
    frequency: '15m' as const,
    contract,
  }
}


function currentResponse(contract: string): SubingStrategyCurrentResponse {
  const entry = { ...historicalAction(), contract }
  return {
    strategy_id: 'subing_strategy_v1',
    formula_version: 'subing_strategy_15m_v1',
    series_kind: 'actual_dominant',
    symbol: 'jm',
    frequency: '15m',
    contract,
    segment_start_trading_day: '2026-08-01',
    source_mode: 'canonical_live',
    cutoff: '2026-08-14T13:30:00Z',
    position_state: 'long',
    pending_action: null,
    current_episode: {
      episode_id: entry.episode_id,
      direction: 'long',
      entry_action: entry,
      exit_action: null,
      state: 'open',
      holding_bar_count: 1,
      reference_change_percent: null,
      current_reference_change_percent: 0,
      latest_reference_price: 100,
      exit_reason_codes: [],
      structure_exit_available: false,
    },
    latest_completed_episode: null,
    direction_context: {
      symbol: 'jm',
      target_trading_day: '2026-08-15',
      source_trading_day: '2026-08-14',
      direction: 'long_only',
      reason_codes: [],
      daily_bar_end: null,
      hourly_bar_end: null,
      physical_contract: contract,
    },
  }
}
