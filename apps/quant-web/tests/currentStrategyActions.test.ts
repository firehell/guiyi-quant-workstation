import assert from 'node:assert/strict'
import test from 'node:test'

import { useSubingWorkbench } from '../src/composables/useSubingWorkbench.ts'
import type { CurrentStrategyActionItem } from '../src/api/alerts.ts'


function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((resolvePromise) => { resolve = resolvePromise })
  return { promise, resolve }
}

function currentItem(id = 1): CurrentStrategyActionItem {
  return {
    id,
    rule_code: 'subing_strategy_v1',
    display_name: '苏冰策略',
    product_name: '焦煤',
    symbol: 'jm',
    contract: 'JM2609',
    trading_day: '2026-08-15',
    frequency: '15m',
    bar_end: '2026-08-15T02:30:00Z',
    result_codes: ['open_long'],
    action_id: 'subing-action:test',
    strategy_action: {
      schema_version: 1,
      strategy_id: 'subing_strategy_v1',
      formula_version: 'subing_strategy_15m_v1',
      action_id: 'subing-action:test',
      episode_id: 'subing-episode:test',
      kind: 'open_long',
      symbol: 'jm',
      contract: 'JM2609',
      trading_day: '2026-08-15',
      segment_start_trading_day: '2026-08-01',
      opportunity_id: 'subing-opportunity:test',
      decision_at: '2026-08-15T02:30:00Z',
      effective_open_at: '2026-08-15T02:30:00Z',
      effective_bar_end: '2026-08-15T02:45:00Z',
      reference_price: '100',
      fill_basis: 'next_bar_open',
      confirmation_source: 'formal_v1',
      reason_codes: [],
      direction_context_source_day: '2026-08-14',
      direction_context_target_day: '2026-08-15',
      bound_reference_pivot: null,
      entry: null,
      holding_bar_count: null,
      reference_change_percent: null,
    },
    detected_at: '2026-08-15T02:30:01Z',
    notification_attempted_at: null,
  }
}


test('keeps ready empty distinct from unavailable', async () => {
  const ready = useSubingWorkbench({
    fetchStrategyActions: async () => ({ status: 'ready', trading_day: '2026-08-15', items: [] }),
    fetchDailyWatch: async () => ({ status: 'unavailable', snapshot: null }),
  })
  await ready.refreshAll()
  assert.equal(ready.strategyStatus.value, 'ready')
  assert.equal(ready.strategyTradingDay.value, '2026-08-15')
  assert.deepEqual(ready.strategyItems.value, [])

  const unavailable = useSubingWorkbench({
    fetchStrategyActions: async () => ({ status: 'unavailable', trading_day: null, items: [] }),
    fetchDailyWatch: async () => ({ status: 'unavailable', snapshot: null }),
  })
  await unavailable.refreshAll()
  assert.equal(unavailable.strategyStatus.value, 'unavailable')
})


test('preserves the last successful Strategy Event snapshot as stale until recovery', async () => {
  let attempt = 0
  const state = useSubingWorkbench({
    fetchStrategyActions: async () => {
      attempt += 1
      if (attempt === 2) throw new Error('temporarily unavailable')
      return {
        status: 'ready' as const,
        trading_day: attempt === 1 ? '2026-08-15' : '2026-08-16',
        items: [currentItem(attempt)],
      }
    },
    fetchDailyWatch: async () => ({ status: 'unavailable', snapshot: null }),
  })

  await state.refreshAll()
  await state.refreshAll()
  assert.equal(state.strategyTradingDay.value, '2026-08-15')
  assert.deepEqual(state.strategyItems.value.map((item) => item.id), [1])
  assert.equal(state.strategyStale.value, true)

  await state.refreshAll()
  assert.equal(state.strategyTradingDay.value, '2026-08-16')
  assert.equal(state.strategyStale.value, false)
})


test('rejects an older all-product Strategy Event response after a newer refresh', async () => {
  const first = deferred<ReturnType<typeof response>>()
  const second = deferred<ReturnType<typeof response>>()
  let attempt = 0
  const state = useSubingWorkbench({
    fetchStrategyActions: () => (attempt++ === 0 ? first.promise : second.promise),
    fetchDailyWatch: async () => ({ status: 'unavailable', snapshot: null }),
  })

  const olderRefresh = state.refreshAll()
  const newerRefresh = state.refreshAll()
  first.resolve(response('2026-08-14', 1))
  await olderRefresh
  assert.equal(state.strategyLoading.value, true)
  assert.equal(state.strategyStatus.value, null)

  second.resolve(response('2026-08-15', 2))
  await newerRefresh
  assert.equal(state.strategyLoading.value, false)
  assert.equal(state.strategyTradingDay.value, '2026-08-15')
  assert.deepEqual(state.strategyItems.value.map((item) => item.id), [2])
})


function response(tradingDay: string, id: number) {
  return {
    status: 'ready' as const,
    trading_day: tradingDay,
    items: [currentItem(id)],
  }
}
