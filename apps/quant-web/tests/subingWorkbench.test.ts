import assert from 'node:assert/strict'
import { it } from 'node:test'

import { useSubingWorkbench } from '../src/composables/useSubingWorkbench.ts'
import type { SubingDailyWatchCurrentResponse } from '../src/types/market.ts'


it('owns Daily Watch and current Strategy Actions without restoring formal signals', async () => {
  const response = { status: 'unavailable', snapshot: null } as SubingDailyWatchCurrentResponse
  const controller = useSubingWorkbench({
    fetchStrategyActions: async () => ({ status: 'unavailable', trading_day: null, items: [] }),
    fetchDailyWatch: async () => response,
  })

  await controller.refreshAll()

  assert.equal(controller.dailyWatch.value, response)
  assert.equal(controller.strategyStatus.value, 'unavailable')
  assert.equal('formalItems' in controller, false)
  controller.dispose()
})


it('preserves the latest Daily Watch snapshot when a refresh fails', async () => {
  const response = { status: 'unavailable', snapshot: null } as SubingDailyWatchCurrentResponse
  let fail = false
  const controller = useSubingWorkbench({
    fetchStrategyActions: async () => ({ status: 'ready', trading_day: '2026-08-15', items: [] }),
    fetchDailyWatch: async () => {
      if (fail) throw new Error('unavailable')
      return response
    },
  })
  await controller.refreshAll()
  fail = true
  await controller.refreshOperational()

  assert.equal(controller.dailyWatch.value, response)
  assert.equal(controller.dailyStale.value, true)
  controller.dispose()
})
