import assert from 'node:assert/strict'
import test from 'node:test'
import {
  defaultMarketWorkspacePreferences,
  loadMarketWorkspacePreferences,
  saveMarketWorkspacePreferences,
} from '../src/utils/marketWorkspacePreferences.ts'

test('corrupt workspace state falls back to defaults', () => {
  const storage = { getItem: () => '{bad' }

  assert.deepEqual(loadMarketWorkspacePreferences(storage), defaultMarketWorkspacePreferences())
})

test('legacy watchlist values are ignored and never saved back to workspace preferences', () => {
  const storage = {
    getItem: () => JSON.stringify({
      version: 1,
      symbol: ' JM ',
      seriesKind: 'contract',
      researchSidebarOpen: false,
      watchlist: [' jm ', 'JM', '', 1],
    }),
  }

  const preferences = loadMarketWorkspacePreferences(storage)
  assert.deepEqual(preferences, {
    version: 1,
    symbol: 'jm',
    seriesKind: 'actual_dominant',
    frequency: '15m',
    researchSidebarOpen: false,
  })

  let saved = ''
  saveMarketWorkspacePreferences(preferences, { setItem: (_key, value) => { saved = value } })
  assert.equal(JSON.parse(saved).watchlist, undefined)
})

test('storage write failures never escape the interaction path', () => {
  assert.doesNotThrow(() => {
    saveMarketWorkspacePreferences(defaultMarketWorkspacePreferences(), {
      setItem: () => { throw new Error('quota') },
    })
  })
})
