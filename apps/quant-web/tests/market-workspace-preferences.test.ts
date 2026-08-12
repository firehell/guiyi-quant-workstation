import assert from 'node:assert/strict'
import test from 'node:test'
import {
  defaultMarketWorkspacePreferences,
  loadMarketWorkspacePreferences,
  saveMarketWorkspacePreferences,
  toggleWatchlistSymbol,
} from '../src/utils/marketWorkspacePreferences.ts'

test('corrupt workspace state falls back to defaults', () => {
  const storage = { getItem: () => '{bad' }

  assert.deepEqual(loadMarketWorkspacePreferences(storage), defaultMarketWorkspacePreferences())
})

test('watchlist normalizes and toggles one symbol', () => {
  const added = toggleWatchlistSymbol(defaultMarketWorkspacePreferences(), ' JM ')

  assert.deepEqual(added.watchlist, ['jm'])
  assert.deepEqual(toggleWatchlistSymbol(added, 'jm').watchlist, [])
})

test('invalid persisted values are normalized without blocking the workspace', () => {
  const storage = {
    getItem: () => JSON.stringify({
      version: 1,
      symbol: ' JM ',
      seriesKind: 'contract',
      researchSidebarOpen: false,
      watchlist: [' jm ', 'JM', '', 1],
    }),
  }

  assert.deepEqual(loadMarketWorkspacePreferences(storage), {
    version: 1,
    symbol: 'jm',
    seriesKind: 'actual_dominant',
    researchSidebarOpen: false,
    watchlist: ['jm'],
  })
})

test('storage write failures never escape the interaction path', () => {
  assert.doesNotThrow(() => {
    saveMarketWorkspacePreferences(defaultMarketWorkspacePreferences(), {
      setItem: () => { throw new Error('quota') },
    })
  })
})
