import assert from 'node:assert/strict'
import test from 'node:test'

import { loadMarketHomePreferences, MARKET_HOME_PREFERENCES_KEY, saveMarketHomePreferences } from '../src/utils/marketHomePreferences.ts'

const defaultPreferences = {
  version: 1,
  sector: '',
  sort: 'default',
  sortDirection: 'desc',
  compactDensity: false,
  detailFrequency: '1d',
  focusRailCollapsed: true,
}

function useStorage(storage: Pick<Storage, 'getItem' | 'setItem'>): void {
  Object.defineProperty(globalThis, 'localStorage', { configurable: true, value: storage })
}

test('uses collapsed observation and descending sort for a new user', () => {
  const values = new Map<string, string>()
  useStorage({ getItem: (key) => values.get(key) ?? null, setItem: (key, value) => values.set(key, value) })

  assert.deepEqual(loadMarketHomePreferences(), defaultPreferences)
})

test('preserves valid version 1 preferences while defaulting a missing direction to descending', () => {
  const values = new Map<string, string>()
  useStorage({ getItem: (key) => values.get(key) ?? null, setItem: (key, value) => values.set(key, value) })
  values.set(MARKET_HOME_PREFERENCES_KEY, JSON.stringify({
    version: 1,
    sector: 'black',
    sort: 'event',
    compactDensity: true,
    detailFrequency: '15m',
    focusRailCollapsed: false,
  }))

  assert.deepEqual(loadMarketHomePreferences(), {
    version: 1,
    sector: 'black',
    sort: 'event',
    sortDirection: 'desc',
    compactDensity: true,
    detailFrequency: '15m',
    focusRailCollapsed: false,
  })
})

test('accepts close and ascending preferences while returning only whitelisted fields', () => {
  const values = new Map<string, string>()
  useStorage({ getItem: (key) => values.get(key) ?? null, setItem: (key, value) => values.set(key, value) })
  values.set(MARKET_HOME_PREFERENCES_KEY, JSON.stringify({
    version: 1,
    sector: 'precious',
    sort: 'close',
    sortDirection: 'asc',
    compactDensity: false,
    detailFrequency: '1w',
    focusRailCollapsed: false,
    injected: 'must-not-survive',
  }))

  assert.deepEqual(loadMarketHomePreferences(), {
    version: 1,
    sector: 'precious',
    sort: 'close',
    sortDirection: 'asc',
    compactDensity: false,
    detailFrequency: '1w',
    focusRailCollapsed: false,
  })
})

test('falls back to safe defaults for corrupt, unknown, or invalid preferences', () => {
  const values = new Map<string, string>()
  useStorage({ getItem: (key) => values.get(key) ?? null, setItem: (key, value) => values.set(key, value) })

  values.set(MARKET_HOME_PREFERENCES_KEY, '{not-json')
  assert.deepEqual(loadMarketHomePreferences(), defaultPreferences)
  values.set(MARKET_HOME_PREFERENCES_KEY, JSON.stringify({ version: 2, sector: 'black', sort: 'event' }))
  assert.deepEqual(loadMarketHomePreferences(), defaultPreferences)
  values.set(MARKET_HOME_PREFERENCES_KEY, JSON.stringify({
    version: 1,
    sector: 'black',
    sort: 'close',
    sortDirection: 'sideways',
    compactDensity: false,
    detailFrequency: '1d',
    focusRailCollapsed: false,
  }))
  assert.deepEqual(loadMarketHomePreferences(), defaultPreferences)
})

test('writes only normalized preference fields and safely ignores blocked storage', () => {
  const values = new Map<string, string>()
  useStorage({ getItem: (key) => values.get(key) ?? null, setItem: (key, value) => values.set(key, value) })
  const preferenceWithExtra = {
    version: 1,
    sector: 'black',
    sort: 'close',
    sortDirection: 'asc',
    compactDensity: true,
    detailFrequency: '60m',
    focusRailCollapsed: false,
    injected: 'must-not-be-written',
  } as const
  saveMarketHomePreferences(preferenceWithExtra)
  assert.deepEqual(JSON.parse(values.get(MARKET_HOME_PREFERENCES_KEY)!), {
    version: 1,
    sector: 'black',
    sort: 'close',
    sortDirection: 'asc',
    compactDensity: true,
    detailFrequency: '60m',
    focusRailCollapsed: false,
  })

  useStorage({ getItem: () => { throw new Error('blocked') }, setItem: () => { throw new Error('blocked') } })
  assert.deepEqual(loadMarketHomePreferences(), defaultPreferences)
  assert.doesNotThrow(() => saveMarketHomePreferences(defaultPreferences))
})
