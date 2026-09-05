import assert from 'node:assert/strict'
import test from 'node:test'

import {
  marketDetailEventIdentity,
  parseMarketDetailRoute,
  resolveViewSwitchIdentity,
  serializeMarketDetailIdentity,
} from '../src/utils/marketDetailRoute.ts'

test('keeps a no-view route on the Legacy transition path', () => {
  assert.deepEqual(parseMarketDetailRoute({ symbol: 'jm' }), {
    kind: 'missing-view', symbol: 'jm',
  })
})

test('trend and subing inject only their omitted fixed identities', () => {
  assert.deepEqual(parseMarketDetailRoute({ view: 'trend', symbol: 'jm' }), {
    kind: 'valid',
    identity: { view: 'trend', symbol: 'jm', seriesKind: 'actual_dominant', frequency: '1d' },
  })
  assert.deepEqual(parseMarketDetailRoute({
    view: 'subing', symbol: 'jm', focus_bar_end: '2026-09-02T02:45:00Z',
  }), {
    kind: 'valid',
    identity: {
      view: 'subing', symbol: 'jm', seriesKind: 'actual_dominant', frequency: '15m',
      focusBarEnd: '2026-09-02T02:45:00Z',
    },
  })
})

test('roundtrips a completed D1 Trend focus through the typed generic route', () => {
  const identity = { view: 'trend' as const, symbol: 'rb', seriesKind: 'actual_dominant' as const,
    frequency: '1d' as const, focusBarEnd: '2026-09-02T07:00:00Z' }
  assert.deepEqual(parseMarketDetailRoute(serializeMarketDetailIdentity(identity)), { kind: 'valid', identity })
})

test('rejects explicit fixed-view identity conflicts without correcting the URL', () => {
  assert.deepEqual(parseMarketDetailRoute({
    view: 'trend', symbol: 'jm', series_kind: 'actual_dominant', frequency: '15m',
  }).kind, 'invalid')
  assert.deepEqual(parseMarketDetailRoute({
    view: 'subing', symbol: 'jm', series_kind: 'continuous', frequency: '15m',
  }).kind, 'invalid')
})

test('validates flexible identities and requires a contract only for contract series', () => {
  assert.deepEqual(parseMarketDetailRoute({
    view: 'htdy', symbol: 'jm', series_kind: 'continuous', frequency: '60m',
  }), {
    kind: 'valid',
    identity: { view: 'htdy', symbol: 'jm', seriesKind: 'continuous', frequency: '60m' },
  })
  assert.deepEqual(parseMarketDetailRoute({
    view: 'free', symbol: 'jm', series_kind: 'contract', frequency: '1d', contract: 'JM2601',
  }), {
    kind: 'valid',
    identity: { view: 'free', symbol: 'jm', seriesKind: 'contract', contract: 'JM2601', frequency: '1d' },
  })
  assert.equal(parseMarketDetailRoute({
    view: 'free', symbol: 'jm', series_kind: 'contract', frequency: '1d',
  }).kind, 'invalid')
  assert.equal(parseMarketDetailRoute({ view: 'free', symbol: 'jm' }).kind, 'invalid')
})

test('fails closed for unknown values and malformed route fields', () => {
  for (const query of [
    { view: 'unknown', symbol: 'jm', series_kind: 'actual_dominant', frequency: '1d' },
    { view: 'free', symbol: 'jm1', series_kind: 'actual_dominant', frequency: '1d' },
    { view: 'free', symbol: 'jm', series_kind: 'invalid', frequency: '1d' },
    { view: 'free', symbol: 'jm', series_kind: 'actual_dominant', frequency: '2h' },
    { view: 'htdy', symbol: 'jm', series_kind: 'actual_dominant', frequency: '15m', focus_bar_end: '2026-02-30T02:45:00Z' },
    { view: 'trend', symbol: 'jm', focus_bar_end: 'not-an-instant' },
    { view: 'free', symbol: 'jm', series_kind: 'actual_dominant', frequency: '15m', focus_bar_end: '2026-09-02T02:45:00Z' },
  ]) assert.equal(parseMarketDetailRoute(query).kind, 'invalid')
})

test('serializes only concrete contract and allowed focus fields', () => {
  assert.deepEqual(serializeMarketDetailIdentity({
    view: 'htdy', symbol: 'jm', seriesKind: 'actual_dominant', frequency: '30m',
    contract: 'ignored', focusBarEnd: '2026-09-02T02:45:00Z',
  }), {
    view: 'htdy', symbol: 'jm', series_kind: 'actual_dominant', contract: undefined,
    frequency: '30m', focus_bar_end: '2026-09-02T02:45:00Z',
  })
})

test('switching views uses fixed identities and only restores flexible view state', () => {
  const restore = {
    htdy: { seriesKind: 'continuous' as const, frequency: '60m' as const },
    free: { seriesKind: 'actual_dominant' as const, frequency: '5m' as const },
  }
  assert.deepEqual(resolveViewSwitchIdentity('trend', 'rb', null, restore), {
    view: 'trend', symbol: 'rb', seriesKind: 'actual_dominant', frequency: '1d',
  })
  assert.deepEqual(resolveViewSwitchIdentity('free', 'rb', null, restore), {
    view: 'free', symbol: 'rb', seriesKind: 'actual_dominant', frequency: '5m',
  })
})

test('reselecting a flexible view preserves its same-symbol contract identity', () => {
  const restore = {
    htdy: { seriesKind: 'continuous' as const, frequency: '60m' as const },
    free: { seriesKind: 'actual_dominant' as const, frequency: '5m' as const },
  }
  for (const view of ['free', 'htdy'] as const) {
    assert.deepEqual(resolveViewSwitchIdentity(view, 'jm', {
      view, symbol: 'jm', seriesKind: 'contract', contract: 'JM2601', frequency: '15m',
    }, restore), {
      view, symbol: 'jm', seriesKind: 'contract', contract: 'JM2601', frequency: '15m',
    })
  }
})

test('switching a flexible contract view to another symbol uses safe restore without old contract', () => {
  const restore = {
    htdy: { seriesKind: 'continuous' as const, frequency: '60m' as const },
    free: { seriesKind: 'actual_dominant' as const, frequency: '5m' as const },
  }
  assert.deepEqual(resolveViewSwitchIdentity('free', 'rb', {
    view: 'free', symbol: 'jm', seriesKind: 'contract', contract: 'JM2601', frequency: '15m',
  }, restore), {
    view: 'free', symbol: 'rb', seriesKind: 'actual_dominant', frequency: '5m',
  })
})

test('events enter their exact view and bar', () => {
  assert.deepEqual(marketDetailEventIdentity({
    id: 1, symbol: 'jm', contract: 'JM2601', trading_day: '2026-09-02', frequency: '30m',
    bar_end: '2026-09-02T02:45:00Z', detected_at: '2026-09-02T02:45:01Z', notification_attempted_at: null,
    rule_code: 'htdy_original_15m', result_codes: ['buy'],
  }), {
    view: 'htdy', symbol: 'jm', seriesKind: 'actual_dominant', frequency: '30m',
    focusBarEnd: '2026-09-02T02:45:00Z',
  })
  assert.deepEqual(marketDetailEventIdentity({
    id: 2, symbol: 'jm', contract: 'JM2601', trading_day: '2026-09-02', frequency: '15m',
    bar_end: '2026-09-02T02:45:00Z', detected_at: '2026-09-02T02:45:01Z', notification_attempted_at: null,
    rule_code: 'subing_ths_alert_15m_v1', result_codes: ['sell'],
  }), {
    view: 'subing', symbol: 'jm', seriesKind: 'actual_dominant', frequency: '15m',
    focusBarEnd: '2026-09-02T02:45:00Z',
  })
})
