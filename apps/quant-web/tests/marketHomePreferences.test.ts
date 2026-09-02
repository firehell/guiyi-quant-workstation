import assert from 'node:assert/strict'
import test from 'node:test'

import { loadMarketHomePreferences, MARKET_HOME_PREFERENCES_KEY } from '../src/utils/marketHomePreferences.ts'

test('falls back to Market Home defaults when local preference is corrupt or invalid', () => {
  const values = new Map<string, string>()
  Object.assign(globalThis, { localStorage: { getItem: (key: string) => values.get(key) ?? null, setItem: (key: string, value: string) => values.set(key, value) } })

  values.set(MARKET_HOME_PREFERENCES_KEY, '{not-json')
  assert.deepEqual(loadMarketHomePreferences(), { version: 1, sector: '', query: '', sort: 'default' })
  values.set(MARKET_HOME_PREFERENCES_KEY, JSON.stringify({ version: 2, sector: 'black', query: '', sort: 'event' }))
  assert.deepEqual(loadMarketHomePreferences(), { version: 1, sector: '', query: '', sort: 'default' })
})
