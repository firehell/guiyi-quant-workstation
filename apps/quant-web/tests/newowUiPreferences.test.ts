import assert from 'node:assert/strict'
import test from 'node:test'
import { readNewowUiPreferences, rememberNewowUiPreferences } from '../src/utils/newowUiPreferences.ts'
test('preferences are identity scoped, patch only display choices and evict older visits', () => {
  rememberNewowUiPreferences('rb:trend', { auxiliary: 'zhaoyao_mirror', scrollTop: 100 })
  rememberNewowUiPreferences('rb:trend', { scrollTop: 250 })
  assert.deepEqual(readNewowUiPreferences('rb:trend'), { auxiliary: 'zhaoyao_mirror', scrollTop: 250 })
  assert.deepEqual(readNewowUiPreferences('jm:trend'), {})
  for (let i = 0; i < 16; i++) rememberNewowUiPreferences(`identity:${i}`, { scrollTop: i })
  assert.deepEqual(readNewowUiPreferences('rb:trend'), {})
})

test('display preferences persist across module visits, ranges stay session-only and reset clears both', async () => {
  const { NEWOW_DISPLAY_KEY, NEWOW_VISIT_KEY, resetNewowUiPreferences } = await import('../src/utils/newowUiPreferences.ts')
  const local = new Map<string, string>(), session = new Map<string, string>()
  const makeStorage = (values: Map<string, string>) => ({ getItem: (key: string) => values.get(key) ?? null, setItem: (key: string, value: string) => values.set(key, value), removeItem: (key: string) => values.delete(key) })
  const previous = Object.getOwnPropertyDescriptor(globalThis, 'window')
  Object.defineProperty(globalThis, 'window', { configurable: true, value: { localStorage: makeStorage(local), sessionStorage: makeStorage(session) } })
  try {
    rememberNewowUiPreferences('jm:trend:1d', { auxiliary: 'main_force_control', scrollTop: 80, chart: { axis: 'price', range: { from: 5, to: 25 }, actions: true, hints: false, structure: false, detail: true } })
    const persistent = JSON.parse(local.get(NEWOW_DISPLAY_KEY)!)['jm:trend:1d']
    assert.equal(persistent.auxiliary, 'main_force_control')
    assert.equal(persistent.scrollTop, undefined)
    assert.equal(persistent.chart.range, null)
    assert.deepEqual(JSON.parse(session.get(NEWOW_VISIT_KEY)!)['jm:trend:1d'].chart.range, { from: 5, to: 25 })
    resetNewowUiPreferences()
    assert.deepEqual(readNewowUiPreferences('jm:trend:1d'), {})
    assert.equal(local.has(NEWOW_DISPLAY_KEY), false)
    assert.equal(session.has(NEWOW_VISIT_KEY), false)
  } finally { if (previous) Object.defineProperty(globalThis, 'window', previous); else Reflect.deleteProperty(globalThis, 'window') }
})

test('invalid browser storage and malformed numeric selections cannot break the page', () => {
  rememberNewowUiPreferences('invalid', { scrollTop: Number.NaN, auxiliary: 'not-real' as any, chart: { axis: 'price', range: { from: 30, to: 2 }, actions: true, hints: false, structure: true, detail: true } })
  assert.deepEqual(readNewowUiPreferences('invalid'), { chart: { axis: 'price', range: null, actions: true, hints: false, structure: true, detail: true } })
})
