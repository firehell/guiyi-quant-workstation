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

test('capability validation rejects unknown versions and mismatched wire fields without fallback', async () => {
  const valid = {
    schema_version: 'newow_product_capabilities_v22', release_stage: 'daily_weekly',
    open_frequencies: ['1d', '1w'], weekly_products: [...candidateWeeklyProducts].sort(),
    deferred_frequencies: [{ frequency: '60m', reason_code: 'NEWOW_HOURLY_RELEASE_PENDING' }],
    open_sections: ['chart', 'auxiliary', 'reference', 'comparator'],
    deferred_sections: [{ section: 'explanation', reason_code: 'NEWOW_CROSS_FREQUENCY_INPUTS_NOT_OPEN' }],
  }
  const invalid = [
    { schema_version: 'newow_product_capabilities_v23' },
    { schema_version: 'toString' },
    { schema_version: null },
    { release_stage: 'daily_weekly_candidate' },
    { open_frequencies: ['1w', '1d'] },
    { open_frequencies: ['1d', '1w', '60m'] },
    { weekly_products: valid.weekly_products.slice(1) },
    { weekly_products: [...valid.weekly_products, 'au'] },
    { weekly_products: candidateWeeklyProducts },
    { deferred_frequencies: [] },
    { deferred_frequencies: [{ frequency: '60m', reason_code: 'NEWOW_WEEKLY_RELEASE_PENDING' }] },
    { deferred_sections: [] },
    { unexpected: true },
  ]
  for (const patch of invalid) {
    await assert.rejects(getNewowProductCapabilities({ request: async () => ({ ...valid, ...patch }) }),
      (error: unknown) => error instanceof Error && 'code' in error && error.code === 'NEWOW_RESPONSE_INVALID')
  }
  const accepted = await getNewowProductCapabilities({ request: async () => structuredClone(valid) })
  assert.ok(Object.isFrozen(accepted))
  assert.ok(Object.isFrozen(accepted.weekly_products))
  assert.ok(Object.isFrozen(accepted.deferred_frequencies[0]))
})

test('black and steel candidate uses its exact allowlist and rejects expanded or malformed scope', async () => {
  const payload = {
    schema_version: 'newow_product_capabilities_v24', release_stage: 'black_steel_intraday_candidate',
    open_frequencies: ['1m', '15m', '30m', '60m', '1d', '1w'],
    intraday_products: ['hc', 'i', 'j', 'jm', 'rb', 'sf', 'sm', 'ss'],
    deferred_frequencies: [], open_sections: ['chart', 'auxiliary', 'reference', 'comparator'],
    deferred_sections: [{ section: 'explanation', reason_code: 'NEWOW_CROSS_FREQUENCY_INPUTS_NOT_OPEN' }],
  }
  const accepted = await getNewowProductCapabilities({ request: async () => structuredClone(payload) })
  assert.ok(Object.isFrozen(accepted.intraday_products))
  const state = useNewowCapabilities(async () => accepted)
  await state.load()
  for (const product of payload.intraday_products) {
    assert.deepEqual(state.openFrequenciesFor(product.toUpperCase()), payload.open_frequencies.filter(item => item !== '1m'))
  }
  assert.deepEqual(state.openFrequenciesFor('au'), [])
  for (const products of [[], ['rb', 'au'], ['rb', 'rb'], ['ss', 'rb'], ['RB']]) {
    await assert.rejects(getNewowProductCapabilities({ request: async () => ({ ...payload, intraday_products: products }) }))
  }
  const subset = await getNewowProductCapabilities({ request: async () => ({ ...payload, intraday_products: ['jm', 'rb'] }) })
  const scoped = useNewowCapabilities(async () => subset)
  await scoped.load()
  assert.deepEqual(scoped.openFrequenciesFor('hc'), [])
  assert.equal(scoped.isFrequencyOpen('1m' as never, 'jm'), false)
})


test('RB and batch new capability versions open the four aggregate periods without 1m', async () => {
  for (const [version, stage] of [['v25', 'rb_intraday_candidate'], ['v26', 'black_steel_intraday_candidate']] as const) {
    const payload = {
      schema_version: `newow_product_capabilities_${version}`, release_stage: stage,
      open_frequencies: ['5m', '15m', '30m', '60m', '1d', '1w'],
      ...(version === 'v26' ? { intraday_products: ['rb'] } : {}),
      deferred_frequencies: [], open_sections: ['chart', 'auxiliary', 'reference', 'comparator'],
      deferred_sections: [{ section: 'explanation', reason_code: 'NEWOW_CROSS_FREQUENCY_INPUTS_NOT_OPEN' }],
    }
    const accepted = await getNewowProductCapabilities({ request: async () => payload })
    const state = useNewowCapabilities(async () => accepted)
    await state.load()
    assert.deepEqual(state.openFrequenciesFor('RB'), payload.open_frequencies)
    assert.deepEqual(state.openFrequenciesFor('au'), [])
    assert.equal(state.isFrequencyOpen('1m' as never, 'rb'), false)
    await assert.rejects(getNewowProductCapabilities({ request: async () => ({ ...payload, open_frequencies: ['1m', '15m', '30m', '60m', '1d', '1w'] }) }))
  }
})


test('single product candidate keeps its scope separate from historical batch and formal capability', async () => {
  const payload = {
    schema_version: 'newow_product_capabilities_v27', release_stage: 'single_product_intraday_candidate',
    open_frequencies: ['5m', '15m', '30m', '60m', '1d', '1w'], intraday_products: ['ma'],
    deferred_frequencies: [], open_sections: ['chart', 'auxiliary', 'reference', 'comparator'],
    deferred_sections: [{ section: 'explanation', reason_code: 'NEWOW_CROSS_FREQUENCY_INPUTS_NOT_OPEN' }],
  }
  const accepted = await getNewowProductCapabilities({ request: async () => structuredClone(payload) })
  const state = useNewowCapabilities(async () => accepted)
  await state.load()
  assert.deepEqual(state.openFrequenciesFor('MA'), payload.open_frequencies)
  assert.deepEqual(state.openFrequenciesFor('rb'), [])
  assert.equal(state.isFrequencyOpen('1m' as never, 'ma'), false)
  const cfAccepted = await getNewowProductCapabilities({ request: async () => ({ ...payload, intraday_products: ['cf'] }) })
  const cfState = useNewowCapabilities(async () => cfAccepted)
  await cfState.load()
  assert.deepEqual(cfState.openFrequenciesFor('CF'), payload.open_frequencies)
  assert.deepEqual(cfState.openFrequenciesFor('ma'), [])
  assert.equal(cfState.isFrequencyOpen('1m' as never, 'cf'), false)
  const oiAccepted = await getNewowProductCapabilities({ request: async () => ({ ...payload, intraday_products: ['oi'] }) })
  const oiState = useNewowCapabilities(async () => oiAccepted)
  await oiState.load()
  assert.deepEqual(oiState.openFrequenciesFor('OI'), payload.open_frequencies)
  assert.deepEqual(oiState.openFrequenciesFor('ma'), [])
  assert.equal(oiState.isFrequencyOpen('1m' as never, 'oi'), false)
  const pAccepted = await getNewowProductCapabilities({ request: async () => ({ ...payload, intraday_products: ['p'] }) })
  const pState = useNewowCapabilities(async () => pAccepted)
  await pState.load()
  assert.deepEqual(pState.openFrequenciesFor('P'), payload.open_frequencies)
  assert.deepEqual(pState.openFrequenciesFor('ma'), [])
  assert.equal(pState.isFrequencyOpen('1m' as never, 'p'), false)
  const lcAccepted = await getNewowProductCapabilities({ request: async () => ({ ...payload, intraday_products: ['lc'] }) })
  const lcState = useNewowCapabilities(async () => lcAccepted)
  await lcState.load()
  assert.deepEqual(lcState.openFrequenciesFor('LC'), payload.open_frequencies)
  assert.deepEqual(lcState.openFrequenciesFor('ma'), [])
  assert.equal(lcState.isFrequencyOpen('1m' as never, 'lc'), false)
  const fgAccepted = await getNewowProductCapabilities({ request: async () => ({ ...payload, intraday_products: ['fg'] }) })
  const fgState = useNewowCapabilities(async () => fgAccepted)
  await fgState.load()
  assert.deepEqual(fgState.openFrequenciesFor('FG'), payload.open_frequencies)
  assert.deepEqual(fgState.openFrequenciesFor('ma'), [])
  assert.equal(fgState.isFrequencyOpen('1m' as never, 'fg'), false)
  for (const products of [['fg', 'ma'], ['fg', 'fg'], ['fg', 'zz']]) {
    await assert.rejects(getNewowProductCapabilities({ request: async () => ({ ...payload, intraday_products: products }) }))
  }
  const aoAccepted = await getNewowProductCapabilities({ request: async () => ({ ...payload, intraday_products: ['ao'] }) })
  const aoState = useNewowCapabilities(async () => aoAccepted)
  await aoState.load()
  assert.deepEqual(aoState.openFrequenciesFor('AO'), payload.open_frequencies)
  assert.deepEqual(aoState.openFrequenciesFor('ma'), [])
  assert.equal(aoState.isFrequencyOpen('1m' as never, 'ao'), false)
  for (const products of [['ao', 'ma'], ['ao', 'ao'], ['ao', 'zz']]) {
    await assert.rejects(getNewowProductCapabilities({ request: async () => ({ ...payload, intraday_products: products }) }))
  }
  const cuAccepted = await getNewowProductCapabilities({ request: async () => ({ ...payload, intraday_products: ['cu'] }) })
  const cuState = useNewowCapabilities(async () => cuAccepted)
  await cuState.load()
  assert.deepEqual(cuState.openFrequenciesFor('CU'), payload.open_frequencies)
  assert.deepEqual(cuState.openFrequenciesFor('ma'), [])
  assert.equal(cuState.isFrequencyOpen('1m' as never, 'cu'), false)
  for (const products of [['cu', 'ma'], ['cu', 'cu'], ['cu', 'zz']]) {
    await assert.rejects(getNewowProductCapabilities({ request: async () => ({ ...payload, intraday_products: products }) }))
  }
  const psAccepted = await getNewowProductCapabilities({ request: async () => ({ ...payload, intraday_products: ['ps'] }) })
  const psState = useNewowCapabilities(async () => psAccepted)
  await psState.load()
  assert.deepEqual(psState.openFrequenciesFor('PS'), payload.open_frequencies)
  assert.deepEqual(psState.openFrequenciesFor('ma'), [])
  assert.equal(psState.isFrequencyOpen('1m' as never, 'ps'), false)
  for (const products of [['ps', 'ma'], ['ps', 'ps'], ['ps', 'zz']]) {
    await assert.rejects(getNewowProductCapabilities({ request: async () => ({ ...payload, intraday_products: products }) }))
  }
  const yAccepted = await getNewowProductCapabilities({ request: async () => ({ ...payload, intraday_products: ['y'] }) })
  const yState = useNewowCapabilities(async () => yAccepted)
  await yState.load()
  assert.deepEqual(yState.openFrequenciesFor('Y'), payload.open_frequencies)
  assert.deepEqual(yState.openFrequenciesFor('ma'), [])
  assert.equal(yState.isFrequencyOpen('1m' as never, 'y'), false)
  for (const products of [['y', 'ma'], ['y', 'y'], ['y', 'zz']]) {
    await assert.rejects(getNewowProductCapabilities({ request: async () => ({ ...payload, intraday_products: products }) }))
  }
  const siAccepted = await getNewowProductCapabilities({ request: async () => ({ ...payload, intraday_products: ['si'] }) })
  const siState = useNewowCapabilities(async () => siAccepted)
  await siState.load()
  assert.deepEqual(siState.openFrequenciesFor('SI'), payload.open_frequencies)
  assert.deepEqual(siState.openFrequenciesFor('ma'), [])
  assert.equal(siState.isFrequencyOpen('1m' as never, 'si'), false)
  for (const products of [['si', 'ma'], ['si', 'si'], ['si', 'zz']]) {
    await assert.rejects(getNewowProductCapabilities({ request: async () => ({ ...payload, intraday_products: products }) }))
  }
  const aAccepted = await getNewowProductCapabilities({ request: async () => ({ ...payload, intraday_products: ['a'] }) })
  const aState = useNewowCapabilities(async () => aAccepted)
  await aState.load()
  assert.deepEqual(aState.openFrequenciesFor('A'), payload.open_frequencies)
  assert.deepEqual(aState.openFrequenciesFor('ma'), [])
  assert.equal(aState.isFrequencyOpen('1m' as never, 'a'), false)
  for (const products of [['a', 'ma'], ['a', 'a'], ['a', 'zz']]) {
    await assert.rejects(getNewowProductCapabilities({ request: async () => ({ ...payload, intraday_products: products }) }))
  }
  const bAccepted = await getNewowProductCapabilities({ request: async () => ({ ...payload, intraday_products: ['b'] }) })
  const bState = useNewowCapabilities(async () => bAccepted)
  await bState.load()
  assert.deepEqual(bState.openFrequenciesFor('B'), payload.open_frequencies)
  assert.deepEqual(bState.openFrequenciesFor('ma'), [])
  assert.equal(bState.isFrequencyOpen('1m' as never, 'b'), false)
  for (const products of [['b', 'ma'], ['b', 'b'], ['b', 'zz']]) {
    await assert.rejects(getNewowProductCapabilities({ request: async () => ({ ...payload, intraday_products: products }) }))
  }
  const bzAccepted = await getNewowProductCapabilities({ request: async () => ({ ...payload, intraday_products: ['bz'] }) })
  const bzState = useNewowCapabilities(async () => bzAccepted)
  await bzState.load()
  assert.deepEqual(bzState.openFrequenciesFor('BZ'), payload.open_frequencies)
  assert.deepEqual(bzState.openFrequenciesFor('ma'), [])
  assert.equal(bzState.isFrequencyOpen('1m' as never, 'bz'), false)
  for (const products of [['bz', 'ma'], ['bz', 'bz'], ['bz', 'zz']]) {
    await assert.rejects(getNewowProductCapabilities({ request: async () => ({ ...payload, intraday_products: products }) }))
  }
  const ebAccepted = await getNewowProductCapabilities({ request: async () => ({ ...payload, intraday_products: ['eb'] }) })
  const ebState = useNewowCapabilities(async () => ebAccepted)
  await ebState.load()
  assert.deepEqual(ebState.openFrequenciesFor('EB'), payload.open_frequencies)
  assert.deepEqual(ebState.openFrequenciesFor('ma'), [])
  assert.equal(ebState.isFrequencyOpen('1m' as never, 'eb'), false)
  for (const products of [['eb', 'ma'], ['eb', 'eb'], ['eb', 'zz']]) {
    await assert.rejects(getNewowProductCapabilities({ request: async () => ({ ...payload, intraday_products: products }) }))
  }
  const ecAccepted = await getNewowProductCapabilities({ request: async () => ({ ...payload, intraday_products: ['ec'] }) })
  const ecState = useNewowCapabilities(async () => ecAccepted)
  await ecState.load()
  assert.deepEqual(ecState.openFrequenciesFor('EC'), payload.open_frequencies)
  assert.deepEqual(ecState.openFrequenciesFor('ma'), [])
  assert.equal(ecState.isFrequencyOpen('1m' as never, 'ec'), false)
  for (const products of [['ec', 'ma'], ['ec', 'ec'], ['ec', 'zz']]) {
    await assert.rejects(getNewowProductCapabilities({ request: async () => ({ ...payload, intraday_products: products }) }))
  }
  const egAccepted = await getNewowProductCapabilities({ request: async () => ({ ...payload, intraday_products: ['eg'] }) })
  const egState = useNewowCapabilities(async () => egAccepted)
  await egState.load()
  assert.deepEqual(egState.openFrequenciesFor('EG'), payload.open_frequencies)
  assert.deepEqual(egState.openFrequenciesFor('ma'), [])
  assert.equal(egState.isFrequencyOpen('1m' as never, 'eg'), false)
  for (const products of [['eg', 'ma'], ['eg', 'eg'], ['eg', 'zz']]) {
    await assert.rejects(getNewowProductCapabilities({ request: async () => ({ ...payload, intraday_products: products }) }))
  }
  const lAccepted = await getNewowProductCapabilities({ request: async () => ({ ...payload, intraday_products: ['l'] }) })
  const lState = useNewowCapabilities(async () => lAccepted)
  await lState.load()
  assert.deepEqual(lState.openFrequenciesFor('L'), payload.open_frequencies)
  assert.deepEqual(lState.openFrequenciesFor('ma'), [])
  assert.equal(lState.isFrequencyOpen('1m' as never, 'l'), false)
  for (const products of [['l', 'ma'], ['l', 'l'], ['l', 'zz']]) {
    await assert.rejects(getNewowProductCapabilities({ request: async () => ({ ...payload, intraday_products: products }) }))
  }
  const pdAccepted = await getNewowProductCapabilities({ request: async () => ({ ...payload, intraday_products: ['pd'] }) })
  const pdState = useNewowCapabilities(async () => pdAccepted)
  await pdState.load()
  assert.deepEqual(pdState.openFrequenciesFor('PD'), payload.open_frequencies)
  assert.deepEqual(pdState.openFrequenciesFor('ma'), [])
  assert.equal(pdState.isFrequencyOpen('1m' as never, 'pd'), false)
  for (const products of [['pd', 'ma'], ['pd', 'pd'], ['pd', 'zz']]) {
    await assert.rejects(getNewowProductCapabilities({ request: async () => ({ ...payload, intraday_products: products }) }))
  }
  const pfAccepted = await getNewowProductCapabilities({ request: async () => ({ ...payload, intraday_products: ['pf'] }) })
  const pfState = useNewowCapabilities(async () => pfAccepted)
  await pfState.load()
  assert.deepEqual(pfState.openFrequenciesFor('PF'), payload.open_frequencies)
  assert.deepEqual(pfState.openFrequenciesFor('ma'), [])
  assert.equal(pfState.isFrequencyOpen('1m' as never, 'pf'), false)
  for (const products of [['pf', 'ma'], ['pf', 'pf'], ['pf', 'zz']]) {
    await assert.rejects(getNewowProductCapabilities({ request: async () => ({ ...payload, intraday_products: products }) }))
  }
  for (const products of [['lc', 'ma'], ['lc', 'lc'], ['lc', 'zz']]) {
    await assert.rejects(getNewowProductCapabilities({ request: async () => ({ ...payload, intraday_products: products }) }))
  }
  for (const products of [['p', 'ma'], ['p', 'p'], ['p', 'zz']]) {
    await assert.rejects(getNewowProductCapabilities({ request: async () => ({ ...payload, intraday_products: products }) }))
  }
  for (const products of [['oi', 'ma'], ['oi', 'oi'], ['oi', 'zz']]) {
    await assert.rejects(getNewowProductCapabilities({ request: async () => ({ ...payload, intraday_products: products }) }))
  }
  for (const products of [['cf', 'ma'], ['cf', 'cf'], ['cf', 'zz']]) {
    await assert.rejects(getNewowProductCapabilities({ request: async () => ({ ...payload, intraday_products: products }) }))
  }
  for (const products of [[], ['rb'], ['ma', 'rb'], ['ma', 'ma'], ['zz'], ['MA']]) {
    await assert.rejects(getNewowProductCapabilities({ request: async () => ({ ...payload, intraday_products: products }) }))
  }
  await assert.rejects(getNewowProductCapabilities({ request: async () => ({ ...payload, schema_version: 'newow_product_capabilities_v26', release_stage: 'black_steel_intraday_candidate' }) }))
})

function historicalMinutes(): NewowProductCapabilities {
  return {
    schema_version: 'newow_product_capabilities_v28', release_stage: 'daily_weekly_intraday_history',
    open_frequencies: ['5m', '15m', '30m', '60m', '1d', '1w'],
    weekly_products: 'a ag al ao ap au b bu bz c cf cj cu eb ec eg fg fu hc i j jd jm l lc lh m ma ni oi p pb pd pf pg pk pl pp pr ps pt px rb rm rs ru sa sc sf sh si sm sn sr ss ta ur v y zn'.split(' '),
    intraday_products: 'rb hc i j jm ma ur ta sh v sa au ag sf sm cj jd ap c lh m rm pk sr cf oi'.split(' ').sort(),
    intraday_as_of: '2026-09-24T07:00:00.000001Z',
    deferred_frequencies: [], open_sections: ['chart', 'auxiliary', 'reference', 'comparator'],
    deferred_sections: [{ section: 'explanation', reason_code: 'NEWOW_CROSS_FREQUENCY_INPUTS_NOT_OPEN' }],
  }
}

test('released historical minutes retain daily weekly for other products and reject scope drift', async () => {
  const capability = await getNewowProductCapabilities({ request: async () => historicalMinutes() })
  const state = useNewowCapabilities(async () => capability)
  await state.load()
  for (const product of capability.intraday_products!) {
    assert.deepEqual(state.openFrequenciesFor(product), ['5m', '15m', '30m', '60m', '1d', '1w'])
    assert.equal(state.isFrequencyOpen('1m' as never, product), false)
  }
  for (const product of ['fu', 'ni', 'ss', 'sc', 'p', 'y']) {
    assert.deepEqual(state.openFrequenciesFor(product), ['1d', '1w'])
  }
  for (const mutation of [
    { intraday_products: [...capability.intraday_products!, 'p'].sort() },
    { intraday_as_of: '2026-09-30T07:00:00.000001Z' },
  ]) {
    await assert.rejects(getNewowProductCapabilities({ request: async () => ({ ...historicalMinutes(), ...mutation }) }))
  }
})
