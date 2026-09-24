import assert from 'node:assert/strict'
import test from 'node:test'

import { useNewowCapabilities } from '../src/composables/useNewowCapabilities.ts'
import { getNewowProductCapabilities } from '../src/api/newowProduct.ts'
import type { NewowProductCapabilities } from '../src/types/newowProduct.ts'

const weeklyProducts = 'a ag al ao ap au bu c cf cu ec fg fu hc i jd jm l lc lh m ma ni p pb pd pp ps pt rb rm ru sa sc sn ss ta ur v y zn'.split(' ')
const candidateWeeklyProducts = [
  ...'a ag al ao ap au b bu bz c cf cu eb ec eg fg fu hc i j jd jm l lc lh m ma ni p pb pd pg pp ps pt rb rm ru sa sc si sn ss ta ur v y zn'.split(' '),
  ...'cj oi pf pk pl pr px rs sf sh sm sr'.split(' '),
]

const daily = (): NewowProductCapabilities => ({
  schema_version: 'newow_product_capabilities_v3',
  release_stage: 'daily',
  open_frequencies: ['1d'],
  deferred_frequencies: [
    { frequency: '1w', reason_code: 'NEWOW_WEEKLY_RELEASE_PENDING' },
    { frequency: '60m', reason_code: 'NEWOW_HOURLY_RELEASE_PENDING' },
  ],
  open_sections: ['chart', 'auxiliary', 'reference', 'comparator'],
  deferred_sections: [{ section: 'explanation', reason_code: 'NEWOW_CROSS_FREQUENCY_INPUTS_NOT_OPEN' }],
})

test('capability loader coalesces reads and exposes only server-open facts', async () => {
  let calls = 0
  const state = useNewowCapabilities(async () => { calls += 1; return daily() })
  await Promise.all([state.load(), state.load()])
  assert.equal(calls, 1)
  assert.equal(state.state.value, 'ready')
  assert.deepEqual(state.openFrequencies.value, ['1d'])
  assert.equal(state.isFrequencyOpen('1w'), false)
  assert.equal(state.isFrequencyOpen('1d'), true)
  assert.equal(state.isFrequencyOpen('60m'), false)
  assert.equal(state.isSectionOpen('reference'), true)
  assert.equal(state.isSectionOpen('explanation'), false)
})

test('capability failure stays unavailable without inventing legacy defaults', async () => {
  const state = useNewowCapabilities(async () => { throw new Error('offline') })
  await state.load()
  assert.equal(state.state.value, 'unavailable')
  assert.deepEqual(state.openFrequencies.value, [])
  assert.equal(state.isFrequencyOpen('1d'), false)
})

test('weekly candidate capability opens W1 only in a candidate response', async () => {
  const state = useNewowCapabilities(async () => ({
    ...daily(),
    schema_version: 'newow_product_capabilities_v4',
    release_stage: 'daily_weekly_candidate',
    open_frequencies: ['1d', '1w'],
    weekly_products: weeklyProducts,
    deferred_frequencies: [
      { frequency: '60m', reason_code: 'NEWOW_HOURLY_RELEASE_PENDING' },
    ],
  }))
  await state.load()
  assert.equal(state.isFrequencyOpen('1w', 'au'), true)
  assert.equal(state.isFrequencyOpen('1w', 'b'), false)
  assert.deepEqual(state.openFrequenciesFor('au'), ['1d', '1w'])
  assert.deepEqual(state.openFrequenciesFor('b'), ['1d'])
  assert.equal(state.isFrequencyOpen('60m'), false)
})

test('remaining19 candidate v9 opens W1 for all isolated candidate products', async () => {
  const state = useNewowCapabilities(async () => ({
    ...daily(),
    schema_version: 'newow_product_capabilities_v9',
    release_stage: 'daily_weekly_candidate',
    open_frequencies: ['1d', '1w'],
    weekly_products: candidateWeeklyProducts,
    deferred_frequencies: [
      { frequency: '60m', reason_code: 'NEWOW_HOURLY_RELEASE_PENDING' },
    ],
  }))
  await state.load()
  assert.equal(state.state.value, 'ready')
  assert.equal(state.isFrequencyOpen('1w', 'au'), true)
  assert.equal(state.isFrequencyOpen('1w', 'b'), true)
  assert.equal(state.isFrequencyOpen('1w', 'sr'), true)
  assert.equal(state.isFrequencyOpen('1w', 'zz'), false)
})

test('formal daily weekly capability opens W1 only for the released 41 products', async () => {
  const state = useNewowCapabilities(async () => ({
    ...daily(),
    schema_version: 'newow_product_capabilities_v8',
    release_stage: 'daily_weekly',
    open_frequencies: ['1d', '1w'],
    weekly_products: weeklyProducts,
    deferred_frequencies: [
      { frequency: '60m', reason_code: 'NEWOW_HOURLY_RELEASE_PENDING' },
    ],
  }))
  await state.load()
  assert.equal(state.isFrequencyOpen('1w', 'au'), true)
  assert.equal(state.isFrequencyOpen('1w', 'b'), false)
  assert.deepEqual(state.openFrequenciesFor('au'), ['1d', '1w'])
  assert.deepEqual(state.openFrequenciesFor('b'), ['1d'])
  assert.equal(state.isFrequencyOpen('60m', 'au'), false)
})

test('formal daily weekly v10 opens W1 for the released 48 products', async () => {
  const released = 'a ag al ao ap au b bu bz c cf cu eb ec eg fg fu hc i j jd jm l lc lh m ma ni p pb pd pg pp ps pt rb rm ru sa sc si sn ss ta ur v y zn'.split(' ')
  const state = useNewowCapabilities(async () => ({
    ...daily(),
    schema_version: 'newow_product_capabilities_v10',
    release_stage: 'daily_weekly',
    open_frequencies: ['1d', '1w'],
    weekly_products: released,
    deferred_frequencies: [
      { frequency: '60m', reason_code: 'NEWOW_HOURLY_RELEASE_PENDING' },
    ],
  }))
  await state.load()
  assert.equal(state.isFrequencyOpen('1w', 'b'), true)
  assert.equal(state.isFrequencyOpen('1w', 'si'), true)
  assert.equal(state.isFrequencyOpen('1w', 'cj'), false)
  assert.deepEqual(state.openFrequenciesFor('pg'), ['1d', '1w'])
  assert.deepEqual(state.openFrequenciesFor('sr'), ['1d'])
})

test('formal daily weekly v11 opens W1 for OI and keeps the other eleven candidates closed', async () => {
  const released = 'a ag al ao ap au b bu bz c cf cu eb ec eg fg fu hc i j jd jm l lc lh m ma ni oi p pb pd pg pp ps pt rb rm ru sa sc si sn ss ta ur v y zn'.split(' ')
  const state = useNewowCapabilities(async () => ({
    ...daily(),
    schema_version: 'newow_product_capabilities_v11',
    release_stage: 'daily_weekly',
    open_frequencies: ['1d', '1w'],
    weekly_products: released,
    deferred_frequencies: [
      { frequency: '60m', reason_code: 'NEWOW_HOURLY_RELEASE_PENDING' },
    ],
  }))
  await state.load()
  assert.equal(state.isFrequencyOpen('1w', 'oi'), true)
  assert.equal(state.isFrequencyOpen('1w', 'cj'), false)
  assert.equal(state.isFrequencyOpen('1w', 'pf'), false)
  assert.deepEqual(state.openFrequenciesFor('oi'), ['1d', '1w'])
})

test('formal daily weekly v12 opens W1 for CJ and keeps the other ten candidates closed', async () => {
  const released = 'a ag al ao ap au b bu bz c cf cj cu eb ec eg fg fu hc i j jd jm l lc lh m ma ni oi p pb pd pg pp ps pt rb rm ru sa sc si sn ss ta ur v y zn'.split(' ')
  const state = useNewowCapabilities(async () => ({
    ...daily(),
    schema_version: 'newow_product_capabilities_v12',
    release_stage: 'daily_weekly',
    open_frequencies: ['1d', '1w'],
    weekly_products: released,
    deferred_frequencies: [
      { frequency: '60m', reason_code: 'NEWOW_HOURLY_RELEASE_PENDING' },
    ],
  }))
  await state.load()
  assert.equal(state.isFrequencyOpen('1w', 'cj'), true)
  assert.equal(state.isFrequencyOpen('1w', 'pf'), false)
  assert.deepEqual(state.openFrequenciesFor('cj'), ['1d', '1w'])
})

test('formal daily weekly v13 opens SR W1 while the other nine remain closed', async () => {
  const released = 'a ag al ao ap au b bu bz c cf cj cu eb ec eg fg fu hc i j jd jm l lc lh m ma ni oi p pb pd pg pp ps pt rb rm ru sa sc si sn sr ss ta ur v y zn'.split(' ')
  const state = useNewowCapabilities(async () => ({
    ...daily(),
    schema_version: 'newow_product_capabilities_v13',
    release_stage: 'daily_weekly',
    open_frequencies: ['1d', '1w'],
    weekly_products: released,
    deferred_frequencies: [
      { frequency: '60m', reason_code: 'NEWOW_HOURLY_RELEASE_PENDING' },
    ],
  }))
  await state.load()
  assert.equal(state.isFrequencyOpen('1w', 'sr'), true)
  assert.equal(state.isFrequencyOpen('1w', 'rs'), false)
  assert.equal(state.isFrequencyOpen('1w', 'pf'), false)
  assert.deepEqual(state.openFrequenciesFor('sr'), ['1d', '1w'])
})

test('formal daily weekly v14 opens RS W1 while the other eight remain closed', async () => {
  const released = 'a ag al ao ap au b bu bz c cf cj cu eb ec eg fg fu hc i j jd jm l lc lh m ma ni oi p pb pd pg pp ps pt rb rm rs ru sa sc si sn sr ss ta ur v y zn'.split(' ')
  const state = useNewowCapabilities(async () => ({
    ...daily(),
    schema_version: 'newow_product_capabilities_v14',
    release_stage: 'daily_weekly',
    open_frequencies: ['1d', '1w'],
    weekly_products: released,
    deferred_frequencies: [
      { frequency: '60m', reason_code: 'NEWOW_HOURLY_RELEASE_PENDING' },
    ],
  }))
  await state.load()
  assert.equal(state.isFrequencyOpen('1w', 'rs'), true)
  assert.equal(state.isFrequencyOpen('1w', 'pf'), false)
  assert.deepEqual(state.openFrequenciesFor('rs'), ['1d', '1w'])
})

test('formal daily weekly v15 opens PK W1 while the other seven remain closed', async () => {
  const released = 'a ag al ao ap au b bu bz c cf cj cu eb ec eg fg fu hc i j jd jm l lc lh m ma ni oi p pb pd pg pk pp ps pt rb rm rs ru sa sc si sn sr ss ta ur v y zn'.split(' ')
  const state = useNewowCapabilities(async () => ({
    ...daily(),
    schema_version: 'newow_product_capabilities_v15',
    release_stage: 'daily_weekly',
    open_frequencies: ['1d', '1w'],
    weekly_products: released,
    deferred_frequencies: [
      { frequency: '60m', reason_code: 'NEWOW_HOURLY_RELEASE_PENDING' },
    ],
  }))
  await state.load()
  assert.equal(state.isFrequencyOpen('1w', 'pk'), true)
  assert.equal(state.isFrequencyOpen('1w', 'pf'), false)
  assert.deepEqual(state.openFrequenciesFor('pk'), ['1d', '1w'])
})

test('formal daily weekly v16 opens PF W1 while the other six remain closed', async () => {
  const released = 'a ag al ao ap au b bu bz c cf cj cu eb ec eg fg fu hc i j jd jm l lc lh m ma ni oi p pb pd pf pg pk pp ps pt rb rm rs ru sa sc si sn sr ss ta ur v y zn'.split(' ')
  const state = useNewowCapabilities(async () => ({
    ...daily(),
    schema_version: 'newow_product_capabilities_v16',
    release_stage: 'daily_weekly',
    open_frequencies: ['1d', '1w'],
    weekly_products: released,
    deferred_frequencies: [
      { frequency: '60m', reason_code: 'NEWOW_HOURLY_RELEASE_PENDING' },
    ],
  }))
  await state.load()
  assert.equal(state.isFrequencyOpen('1w', 'pf'), true)
  assert.equal(state.isFrequencyOpen('1w', 'pl'), false)
  assert.deepEqual(state.openFrequenciesFor('pf'), ['1d', '1w'])
})

test('formal daily weekly v17 opens PL W1 while the other five remain closed', async () => {
  const released = 'a ag al ao ap au b bu bz c cf cj cu eb ec eg fg fu hc i j jd jm l lc lh m ma ni oi p pb pd pf pg pk pl pp ps pt rb rm rs ru sa sc si sn sr ss ta ur v y zn'.split(' ')
  const state = useNewowCapabilities(async () => ({
    ...daily(),
    schema_version: 'newow_product_capabilities_v17',
    release_stage: 'daily_weekly',
    open_frequencies: ['1d', '1w'],
    weekly_products: released,
    deferred_frequencies: [
      { frequency: '60m', reason_code: 'NEWOW_HOURLY_RELEASE_PENDING' },
    ],
  }))
  await state.load()
  assert.equal(state.isFrequencyOpen('1w', 'pl'), true)
  assert.equal(state.isFrequencyOpen('1w', 'pr'), false)
  assert.deepEqual(state.openFrequenciesFor('pl'), ['1d', '1w'])
})

test('formal daily weekly v18 opens PR W1 while the other four remain closed', async () => {
  const released = 'a ag al ao ap au b bu bz c cf cj cu eb ec eg fg fu hc i j jd jm l lc lh m ma ni oi p pb pd pf pg pk pl pp pr ps pt rb rm rs ru sa sc si sn sr ss ta ur v y zn'.split(' ')
  const state = useNewowCapabilities(async () => ({
    ...daily(),
    schema_version: 'newow_product_capabilities_v18',
    release_stage: 'daily_weekly',
    open_frequencies: ['1d', '1w'],
    weekly_products: released,
    deferred_frequencies: [
      { frequency: '60m', reason_code: 'NEWOW_HOURLY_RELEASE_PENDING' },
    ],
  }))
  await state.load()
  assert.equal(state.isFrequencyOpen('1w', 'pr'), true)
  assert.equal(state.isFrequencyOpen('1w', 'px'), false)
  assert.deepEqual(state.openFrequenciesFor('pr'), ['1d', '1w'])
})

test('formal daily weekly v19 opens PX W1 while the other three remain closed', async () => {
  const released = 'a ag al ao ap au b bu bz c cf cj cu eb ec eg fg fu hc i j jd jm l lc lh m ma ni oi p pb pd pf pg pk pl pp pr ps pt px rb rm rs ru sa sc si sn sr ss ta ur v y zn'.split(' ')
  const state = useNewowCapabilities(async () => ({
    ...daily(),
    schema_version: 'newow_product_capabilities_v19',
    release_stage: 'daily_weekly',
    open_frequencies: ['1d', '1w'],
    weekly_products: released,
    deferred_frequencies: [
      { frequency: '60m', reason_code: 'NEWOW_HOURLY_RELEASE_PENDING' },
    ],
  }))
  await state.load()
  assert.equal(state.isFrequencyOpen('1w', 'px'), true)
  assert.equal(state.isFrequencyOpen('1w', 'sf'), false)
  assert.deepEqual(state.openFrequenciesFor('px'), ['1d', '1w'])
})

test('formal daily weekly v20 opens SF W1 while the other two remain closed', async () => {
  const released = 'a ag al ao ap au b bu bz c cf cj cu eb ec eg fg fu hc i j jd jm l lc lh m ma ni oi p pb pd pf pg pk pl pp pr ps pt px rb rm rs ru sa sc sf si sn sr ss ta ur v y zn'.split(' ')
  const state = useNewowCapabilities(async () => ({
    ...daily(),
    schema_version: 'newow_product_capabilities_v20',
    release_stage: 'daily_weekly',
    open_frequencies: ['1d', '1w'],
    weekly_products: released,
    deferred_frequencies: [
      { frequency: '60m', reason_code: 'NEWOW_HOURLY_RELEASE_PENDING' },
    ],
  }))
  await state.load()
  assert.equal(state.isFrequencyOpen('1w', 'sf'), true)
  assert.equal(state.isFrequencyOpen('1w', 'sh'), false)
  assert.deepEqual(state.openFrequenciesFor('sf'), ['1d', '1w'])
})

test('formal daily weekly v21 opens SH W1 while SM remain closed', async () => {
  const released = 'a ag al ao ap au b bu bz c cf cj cu eb ec eg fg fu hc i j jd jm l lc lh m ma ni oi p pb pd pf pg pk pl pp pr ps pt px rb rm rs ru sa sc sf sh si sn sr ss ta ur v y zn'.split(' ')
  const state = useNewowCapabilities(async () => ({
    ...daily(),
    schema_version: 'newow_product_capabilities_v21',
    release_stage: 'daily_weekly',
    open_frequencies: ['1d', '1w'],
    weekly_products: released,
    deferred_frequencies: [
      { frequency: '60m', reason_code: 'NEWOW_HOURLY_RELEASE_PENDING' },
    ],
  }))
  await state.load()
  assert.equal(state.isFrequencyOpen('1w', 'sh'), true)
  assert.equal(state.isFrequencyOpen('1w', 'sm'), false)
  assert.deepEqual(state.openFrequenciesFor('sh'), ['1d', '1w'])
})

test('formal daily weekly v22 opens SM W1 for all 60 products', async () => {
  const released = 'a ag al ao ap au b bu bz c cf cj cu eb ec eg fg fu hc i j jd jm l lc lh m ma ni oi p pb pd pf pg pk pl pp pr ps pt px rb rm rs ru sa sc sf sh si sm sn sr ss ta ur v y zn'.split(' ')
  const state = useNewowCapabilities(async () => ({
    ...daily(),
    schema_version: 'newow_product_capabilities_v22',
    release_stage: 'daily_weekly',
    open_frequencies: ['1d', '1w'],
    weekly_products: released,
    deferred_frequencies: [{ frequency: '60m', reason_code: 'NEWOW_HOURLY_RELEASE_PENDING' }],
  }))
  await state.load()
  assert.equal(state.isFrequencyOpen('1w', 'sm'), true)
  assert.equal(state.isFrequencyOpen('1w', 'zz'), false)
  assert.deepEqual(state.openFrequenciesFor('sm'), ['1d', '1w'])
})

test('AU period preview accepts its exact all-period capability', async () => {
  const payload = {
    ...daily(),
    schema_version: 'newow_product_capabilities_v5',
    release_stage: 'au_daily_weekly_hourly_candidate',
    open_frequencies: ['1d', '1w', '60m'],
    deferred_frequencies: [],
  }
  const accepted = await getNewowProductCapabilities({ request: async () => payload })
  assert.deepEqual(accepted.open_frequencies, ['1d', '1w', '60m'])
  assert.equal(Object.isFrozen(accepted), true)
  const state = useNewowCapabilities(async () => accepted)
  await state.load()
  assert.deepEqual(state.openFrequenciesFor('au'), ['1d', '1w', '60m'])
  assert.deepEqual(state.openFrequenciesFor('jm'), [])
  assert.equal(state.isFrequencyOpen('60m', 'jm'), false)
  assert.equal(state.isFrequencyOpen('60m', 'au'), true)
})

test('AP hourly preview opens 60m only for AP and keeps W1 and other products closed', async () => {
  const payload = {
    ...daily(),
    schema_version: 'newow_product_capabilities_v7',
    release_stage: 'ap_hourly_candidate',
    open_frequencies: ['1d', '60m'],
    deferred_frequencies: [
      { frequency: '1w', reason_code: 'NEWOW_WEEKLY_RELEASE_PENDING' },
    ],
  }
  const accepted = await getNewowProductCapabilities({ request: async () => payload })
  assert.deepEqual(accepted.open_frequencies, ['1d', '60m'])
  const state = useNewowCapabilities(async () => accepted)
  await state.load()
  assert.deepEqual(state.openFrequenciesFor('ap'), ['1d', '60m'])
  assert.deepEqual(state.openFrequenciesFor('pd'), ['1d'])
  assert.deepEqual(state.openFrequenciesFor('pt'), ['1d'])
  assert.deepEqual(state.openFrequenciesFor('au'), ['1d'])
  assert.deepEqual(state.openFrequenciesFor('jm'), ['1d'])
  assert.equal(state.isFrequencyOpen('60m', 'ap'), true)
  assert.equal(state.isFrequencyOpen('60m', 'pd'), false)
  assert.equal(state.isFrequencyOpen('60m', 'pt'), false)
  assert.equal(state.isFrequencyOpen('1w', 'ap'), false)
})

test('PD/PT hourly preview remains scoped to PD and PT', async () => {
  const payload = {
    ...daily(),
    schema_version: 'newow_product_capabilities_v6',
    release_stage: 'pd_pt_hourly_candidate',
    open_frequencies: ['1d', '60m'],
    deferred_frequencies: [
      { frequency: '1w', reason_code: 'NEWOW_WEEKLY_RELEASE_PENDING' },
    ],
  }
  const accepted = await getNewowProductCapabilities({ request: async () => payload })
  const state = useNewowCapabilities(async () => accepted)
  await state.load()
  assert.deepEqual(state.openFrequenciesFor('pd'), ['1d', '60m'])
  assert.deepEqual(state.openFrequenciesFor('pt'), ['1d', '60m'])
  assert.deepEqual(state.openFrequenciesFor('ap'), ['1d'])
  assert.equal(state.isFrequencyOpen('60m', 'au'), false)
})
