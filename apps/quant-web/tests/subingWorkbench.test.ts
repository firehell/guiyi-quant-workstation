import assert from 'node:assert/strict'
import test from 'node:test'
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
    projection_version: 'subing_daily_watch_v2',
    formula_version: 'subing_ema21_rank1_stitched_raw_v2',
    history_mode: 'rank1_stitched_raw',
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
    projection_version: 'subing_daily_watch_v2',
    formula_version: 'subing_ema21_rank1_stitched_raw_v2',
    history_mode: 'rank1_stitched_raw',
    expected_target_trading_day: '2026-08-26',
    latest_target_trading_day: null,
    error_code: 'SUBING_DAILY_WATCH_NOT_GENERATED',
    snapshot: null,
  }
}

test('formal ready-empty remains distinct from unavailable', async () => {
  let response: CurrentFormalSignalsResponse = {
    status: 'ready', trading_day: '2026-08-25', items: [],
  }
  const state = useSubingWorkbench({
    fetchFormal: async () => response,
    fetchDailyWatch: async () => unavailableDaily(),
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

test('Formal and Daily Watch keep independent availability', async () => {
  const state = useSubingWorkbench({
    fetchFormal: async () => formal(1),
    fetchDailyWatch: async () => unavailableDaily(),
  })
  await state.refreshAll()

  assert.equal(state.formalStatus.value, 'ready')
  assert.equal(state.formalItems.value[0]?.id, 1)
  assert.equal(state.dailyWatch.value?.status, 'unavailable')
  state.dispose()
})

test('older Formal and Daily responses cannot overwrite newer generations', async () => {
  const formalFirst = deferred<CurrentFormalSignalsResponse>()
  const formalSecond = deferred<CurrentFormalSignalsResponse>()
  const dailyFirst = deferred<SubingDailyWatchCurrentResponse>()
  const dailySecond = deferred<SubingDailyWatchCurrentResponse>()
  let formalAttempt = 0
  let dailyAttempt = 0
  const state = useSubingWorkbench({
    fetchFormal: () => (formalAttempt++ === 0 ? formalFirst.promise : formalSecond.promise),
    fetchDailyWatch: () => (dailyAttempt++ === 0 ? dailyFirst.promise : dailySecond.promise),
  })

  const older = state.refreshAll()
  const newer = state.refreshAll()
  formalSecond.resolve(formal(2, '2026-08-26'))
  dailySecond.resolve(daily('2026-08-27'))
  await newer
  formalFirst.resolve(formal(1))
  dailyFirst.resolve(daily())
  await older

  assert.equal(state.formalTradingDay.value, '2026-08-26')
  assert.deepEqual(state.formalItems.value.map((item) => item.id), [2])
  assert.equal(state.dailyWatch.value?.snapshot?.target_trading_day, '2026-08-27')
  state.dispose()
})

test('dispose invalidates both pending source responses', async () => {
  const formalPending = deferred<CurrentFormalSignalsResponse>()
  const dailyPending = deferred<SubingDailyWatchCurrentResponse>()
  const state = useSubingWorkbench({
    fetchFormal: () => formalPending.promise,
    fetchDailyWatch: () => dailyPending.promise,
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

test('failed refreshes preserve the last successful source snapshot', async () => {
  let formalAttempt = 0
  let dailyAttempt = 0
  const state = useSubingWorkbench({
    fetchFormal: async () => {
      formalAttempt += 1
      if (formalAttempt === 2) throw new Error('temporary')
      return formal(1)
    },
    fetchDailyWatch: async () => {
      dailyAttempt += 1
      if (dailyAttempt === 2) throw new Error('temporary')
      return daily()
    },
  })

  await state.refreshAll()
  await state.refreshAll()

  assert.equal(state.formalStatus.value, 'ready')
  assert.equal(state.formalStale.value, true)
  assert.equal(state.dailyWatch.value?.status, 'ready')
  assert.equal(state.dailyStale.value, true)
  state.dispose()
})
