import assert from 'node:assert/strict'
import test from 'node:test'
import { nextTick } from 'vue'
import type { CurrentFormalSignalsResponse } from '../src/api/alerts.ts'
import type { SubingDailyWatchCurrentResponse } from '../src/types/market.ts'
import { useSubingWorkbench } from '../src/composables/useSubingWorkbench.ts'

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason?: unknown) => void
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise
    reject = rejectPromise
  })
  return { promise, resolve, reject }
}

function formal(id: number, tradingDay = '2026-08-25'): CurrentFormalSignalsResponse {
  return {
    status: 'ready',
    trading_day: tradingDay,
    items: [{
      id,
      rule_code: id === 1 ? 'subing_entry_signal_v1' : 'htdy_original_15m',
      display_name: id === 1 ? '苏冰' : '火天大有',
      symbol: id === 1 ? 'jm' : 'ag',
      product_name: id === 1 ? '焦煤' : '白银',
      contract: id === 1 ? 'JM2701' : 'AG2701',
      trading_day: tradingDay,
      frequency: '15m',
      bar_end: `${tradingDay}T02:30:00Z`,
      result_codes: ['buy'],
      lower_tf_confirmation: false,
      detected_at: `${tradingDay}T02:31:00Z`,
      notification_attempted_at: null,
    }],
  }
}

function daily(target = '2026-08-26'): SubingDailyWatchCurrentResponse {
  return {
    status: 'ready',
    expected_target_trading_day: target,
    latest_target_trading_day: target,
    error_code: null,
    snapshot: {
      source_trading_day: '2026-08-25',
      target_trading_day: target,
      generated_at: '2026-08-25T10:30:00Z',
      counts: { universe: 1, long_watch: 0, short_watch: 0, excluded: 1, unavailable: 0 },
      long_watch: [], short_watch: [], unavailable: [],
    },
  }
}

function unavailableDaily(): SubingDailyWatchCurrentResponse {
  return {
    status: 'unavailable',
    expected_target_trading_day: '2026-08-26',
    latest_target_trading_day: null,
    error_code: 'SUBING_DAILY_WATCH_NOT_GENERATED',
    snapshot: null,
  }
}

async function settleWatchers() {
  await nextTick()
  await new Promise((resolve) => setTimeout(resolve, 0))
}

test('formal ready-empty remains distinct from unavailable', async () => {
  let response: CurrentFormalSignalsResponse = { status: 'ready', trading_day: '2026-08-25', items: [] }
  const state = useSubingWorkbench({
    fetchFormal: async () => response,
    fetchDailyWatch: async () => unavailableDaily(),
    fetchEventStates: async () => ({ items: [] }),
  })

  await state.refreshAll()
  assert.equal(state.formalStatus.value, 'ready')
  assert.equal(state.formalTradingDay.value, '2026-08-25')
  assert.deepEqual(state.formalItems.value, [])

  response = { status: 'unavailable', trading_day: null, items: [] }
  await state.refreshAll()
  assert.equal(state.formalStatus.value, 'unavailable')
  state.dispose()
})

test('typed Daily Watch unavailability does not clear a ready Formal event', async () => {
  const state = useSubingWorkbench({
    fetchFormal: async () => formal(1),
    fetchDailyWatch: async () => unavailableDaily(),
    fetchEventStates: async () => ({ items: [{ event_id: 1, state: 'pending_decision', decision_id: null, episode_id: null }] }),
  })
  await state.refreshAll()
  await settleWatchers()

  assert.equal(state.formalStatus.value, 'ready')
  assert.deepEqual(Object.keys(state.formalEventStates.value), ['1'])
  assert.equal(state.dailyWatch.value?.status, 'unavailable')
  state.dispose()
})

test('a Formal request failure does not clear a ready Daily Watch snapshot', async () => {
  const state = useSubingWorkbench({
    fetchFormal: async () => { throw new Error('formal unavailable') },
    fetchDailyWatch: async () => daily(),
    fetchEventStates: async () => ({ items: [] }),
  })
  await state.refreshAll()

  assert.equal(state.formalStatus.value, 'unavailable')
  assert.equal(state.dailyWatch.value?.status, 'ready')
  assert.equal(state.dailyWatch.value?.snapshot?.target_trading_day, '2026-08-26')
  state.dispose()
})

test('older Formal and Daily responses cannot overwrite newer primitive generations', async () => {
  const formalFirst = deferred<CurrentFormalSignalsResponse>()
  const formalSecond = deferred<CurrentFormalSignalsResponse>()
  const dailyFirst = deferred<SubingDailyWatchCurrentResponse>()
  const dailySecond = deferred<SubingDailyWatchCurrentResponse>()
  let formalAttempt = 0
  let dailyAttempt = 0
  const state = useSubingWorkbench({
    fetchFormal: () => (formalAttempt++ === 0 ? formalFirst.promise : formalSecond.promise),
    fetchDailyWatch: () => (dailyAttempt++ === 0 ? dailyFirst.promise : dailySecond.promise),
    fetchEventStates: async () => ({ items: [] }),
  })

  const older = state.refreshAll()
  const newer = state.refreshAll()
  formalSecond.resolve(formal(2, '2026-08-26'))
  dailySecond.resolve(daily('2026-08-27'))
  await newer
  formalFirst.resolve(formal(1, '2026-08-25'))
  dailyFirst.resolve(daily('2026-08-26'))
  await older

  assert.equal(state.formalTradingDay.value, '2026-08-26')
  assert.deepEqual(state.formalItems.value.map((item) => item.id), [2])
  assert.equal(state.dailyWatch.value?.snapshot?.target_trading_day, '2026-08-27')
  state.dispose()
})

test('Formal event-state lookup is cleared and older lookup is invalidated when items change', async () => {
  const firstLookup = deferred<{ items: Array<{ event_id: number, state: 'pending_decision', decision_id: null, episode_id: null }> }>()
  const secondLookup = deferred<{ items: Array<{ event_id: number, state: 'pending_decision', decision_id: null, episode_id: null }> }>()
  let formalAttempt = 0
  let lookupAttempt = 0
  const state = useSubingWorkbench({
    fetchFormal: async () => formal(++formalAttempt),
    fetchDailyWatch: async () => daily(),
    fetchEventStates: () => {
      lookupAttempt += 1
      if (lookupAttempt === 1) return firstLookup.promise
      return secondLookup.promise
    },
  })

  await state.refreshAll()
  await nextTick()
  await state.refreshAll()
  assert.deepEqual(state.formalEventStates.value, {})
  secondLookup.resolve({ items: [{ event_id: 2, state: 'pending_decision', decision_id: null, episode_id: null }] })
  await settleWatchers()
  assert.deepEqual(Object.keys(state.formalEventStates.value), ['2'])
  firstLookup.resolve({ items: [{ event_id: 1, state: 'pending_decision', decision_id: null, episode_id: null }] })
  await settleWatchers()
  assert.deepEqual(Object.keys(state.formalEventStates.value), ['2'])
  state.dispose()
})

test('a fresh Formal array with the same event-id set keeps old states while replacement lookup is pending or fails', async () => {
  const replacementLookup = deferred<{ items: Array<{ event_id: number, state: 'pending_decision', decision_id: null, episode_id: null }> }>()
  let formalAttempt = 0
  let lookupAttempt = 0
  const state = useSubingWorkbench({
    fetchFormal: async () => {
      formalAttempt += 1
      const items = [formal(1).items[0], formal(2).items[0]]
      return {
        status: 'ready' as const,
        trading_day: '2026-08-25',
        items: formalAttempt === 1 ? items : [...items].reverse(),
      }
    },
    fetchDailyWatch: async () => daily(),
    fetchEventStates: async () => {
      lookupAttempt += 1
      if (lookupAttempt === 1) return {
        items: [
          { event_id: 1, state: 'pending_decision' as const, decision_id: null, episode_id: null },
          { event_id: 2, state: 'pending_decision' as const, decision_id: null, episode_id: null },
        ],
      }
      if (lookupAttempt === 2) return replacementLookup.promise
      throw new Error('event states temporarily unavailable')
    },
  })

  await state.refreshAll()
  await settleWatchers()
  assert.deepEqual(Object.keys(state.formalEventStates.value).sort(), ['1', '2'])

  await state.refreshAll()
  assert.deepEqual(Object.keys(state.formalEventStates.value).sort(), ['1', '2'])
  replacementLookup.resolve({
    items: [
      { event_id: 1, state: 'pending_decision', decision_id: null, episode_id: null },
      { event_id: 2, state: 'pending_decision', decision_id: null, episode_id: null },
    ],
  })
  await settleWatchers()

  await state.refreshAll()
  await settleWatchers()
  assert.deepEqual(Object.keys(state.formalEventStates.value).sort(), ['1', '2'])
  state.dispose()
})

test('a changed Formal event-id set stays empty when its event-state lookup fails', async () => {
  let formalAttempt = 0
  const state = useSubingWorkbench({
    fetchFormal: async () => formal(++formalAttempt),
    fetchDailyWatch: async () => daily(),
    fetchEventStates: async (ids) => {
      if (ids[0] === 1) return { items: [{ event_id: 1, state: 'pending_decision', decision_id: null, episode_id: null }] }
      throw new Error('event states unavailable')
    },
  })

  await state.refreshAll()
  await settleWatchers()
  assert.deepEqual(Object.keys(state.formalEventStates.value), ['1'])

  await state.refreshAll()
  assert.deepEqual(state.formalEventStates.value, {})
  await settleWatchers()
  assert.deepEqual(state.formalEventStates.value, {})
  state.dispose()
})

test('refreshOperational refreshes only the Formal and Daily primitives', async () => {
  const calls = { formal: 0, daily: 0, states: 0 }
  const state = useSubingWorkbench({
    fetchFormal: async () => { calls.formal += 1; return { status: 'ready', trading_day: '2026-08-25', items: [] } },
    fetchDailyWatch: async () => { calls.daily += 1; return daily() },
    fetchEventStates: async () => { calls.states += 1; return { items: [] } },
  })
  await state.refreshOperational()
  await settleWatchers()

  assert.deepEqual(calls, { formal: 1, daily: 1, states: 0 })
  state.dispose()
})

test('dispose invalidates both pending source responses', async () => {
  const formalPending = deferred<CurrentFormalSignalsResponse>()
  const dailyPending = deferred<SubingDailyWatchCurrentResponse>()
  const state = useSubingWorkbench({
    fetchFormal: () => formalPending.promise,
    fetchDailyWatch: () => dailyPending.promise,
    fetchEventStates: async () => ({ items: [] }),
  })
  const refresh = state.refreshAll()
  state.dispose()
  formalPending.resolve(formal(1))
  dailyPending.resolve(daily())
  await refresh

  assert.equal(state.formalStatus.value, null)
  assert.equal(state.dailyWatch.value, null)
  assert.equal(state.formalLoading.value, false)
  assert.equal(state.dailyLoading.value, false)
})

test('the workbench preserves every backend Formal item without rule filtering or re-evaluation', async () => {
  const response = formal(1)
  response.items.push(formal(2).items[0])
  const state = useSubingWorkbench({
    fetchFormal: async () => response,
    fetchDailyWatch: async () => daily(),
    fetchEventStates: async () => ({ items: [] }),
  })
  await state.refreshAll()

  assert.deepEqual(state.formalItems.value, response.items)
  state.dispose()
})

test('a failed Formal refresh preserves its last snapshot and exposes source-specific stale state', async () => {
  let attempt = 0
  const state = useSubingWorkbench({
    fetchFormal: async () => {
      attempt += 1
      if (attempt === 2) throw new Error('temporary')
      return formal(1)
    },
    fetchDailyWatch: async () => daily(),
    fetchEventStates: async () => ({ items: [] }),
  })
  await state.refreshAll()
  await state.refreshAll()

  assert.equal(state.formalStatus.value, 'ready')
  assert.equal(state.formalTradingDay.value, '2026-08-25')
  assert.deepEqual(state.formalItems.value.map((item) => item.id), [1])
  assert.equal(state.formalStale.value, true)
  assert.equal(state.dailyStale.value, false)
  state.dispose()
})

test('a failed Daily refresh preserves its last snapshot and a later success clears stale', async () => {
  let dailyAttempt = 0
  const state = useSubingWorkbench({
    fetchFormal: async () => ({ status: 'ready', trading_day: '2026-08-25', items: [] }),
    fetchDailyWatch: async () => {
      dailyAttempt += 1
      if (dailyAttempt === 2) throw new Error('temporary')
      return daily(dailyAttempt === 1 ? '2026-08-26' : '2026-08-27')
    },
    fetchEventStates: async () => ({ items: [] }),
  })

  await state.refreshAll()
  await state.refreshAll()
  assert.equal(state.dailyWatch.value?.snapshot?.target_trading_day, '2026-08-26')
  assert.equal(state.dailyStale.value, true)

  await state.refreshAll()
  assert.equal(state.dailyWatch.value?.snapshot?.target_trading_day, '2026-08-27')
  assert.equal(state.dailyStale.value, false)
  state.dispose()
})

test('workbench delegates overlapping Formal refreshes directly to one generation owner', async () => {
  const first = deferred<CurrentFormalSignalsResponse>()
  const second = deferred<CurrentFormalSignalsResponse>()
  let attempt = 0
  const state = useSubingWorkbench({
    fetchFormal: () => (attempt++ === 0 ? first.promise : second.promise),
    fetchDailyWatch: async () => daily(),
    fetchEventStates: async () => ({ items: [] }),
  })
  const older = state.refreshOperational()
  const newer = state.refreshOperational()
  second.resolve(formal(2, '2026-08-26'))
  await newer
  first.reject(new Error('older request failed'))
  await older

  assert.equal(attempt, 2)
  assert.equal(state.formalTradingDay.value, '2026-08-26')
  assert.equal(state.formalStale.value, false)
  assert.equal(state.formalLoading.value, false)
  state.dispose()
})
