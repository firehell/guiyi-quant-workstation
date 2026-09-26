import assert from 'node:assert/strict'
import test from 'node:test'

import {
  marketDetailEventIdentity,
  isNewowStrategySwitch,
  parseMarketDetailRoute,
  resolveViewSwitchIdentity,
  serializeMarketDetailIdentity,
} from '../src/utils/marketDetailRoute.ts'

test('migrates an omitted view deterministically to Free', () => {
  assert.deepEqual(parseMarketDetailRoute({ symbol: 'jm' }), {
    kind: 'valid', identity: { view: 'free', symbol: 'jm', seriesKind: 'actual_dominant', frequency: '15m' },
  })
})

test('legacy Trend migrates to the unified Newow trend identity and preserves a legal focus', () => {
  assert.deepEqual(parseMarketDetailRoute({ view: 'trend', symbol: 'jm' }), {
    kind: 'valid',
    identity: { view: 'newow', symbol: 'jm', strategy: 'trend', seriesKind: 'actual_dominant', frequency: '1d' },
  })
  assert.deepEqual(parseMarketDetailRoute({
    view: 'trend', symbol: 'jm', focus_bar_end: '2026-09-02T07:00:00Z',
  }), {
    kind: 'valid',
    identity: {
      view: 'newow', symbol: 'jm', strategy: 'trend', seriesKind: 'actual_dominant', frequency: '1d',
      focusBarEnd: '2026-09-02T07:00:00Z',
    },
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

test('roundtrips a completed Newow focus through the unified route', () => {
  const identity = { view: 'newow' as const, symbol: 'rb', strategy: 'trend' as const,
    seriesKind: 'actual_dominant' as const, frequency: '1d' as const,
    focusBarEnd: '2026-09-02T07:00:00Z' }
  assert.deepEqual(parseMarketDetailRoute(serializeMarketDetailIdentity(identity)), { kind: 'valid', identity })
})

test('SuBing research routes accept only four actual dominant periods', () => {
  for (const frequency of ['15m', '30m', '60m', '1d']) {
    const parsed = parseMarketDetailRoute({ view: 'subing', symbol: 'jm', series_kind: 'actual_dominant', frequency })
    assert.equal(parsed.kind, 'valid')
    if (parsed.kind === 'valid') assert.equal(parsed.identity.frequency, frequency)
  }
  for (const frequency of ['1m', '5m', '1w']) {
    assert.equal(parseMarketDetailRoute({ view: 'subing', symbol: 'jm', series_kind: 'actual_dominant', frequency }).kind, 'invalid')
  }
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
    { view: 'free', symbol: 'jm', series_kind: 'continuous', frequency: '15m', focus_bar_end: '2026-09-02T02:45:00Z' },
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

test('switching views restores only active unified view state', () => {
  const restore = {
    newow: { strategy: 'main_rise' as const, frequency: '1w' as const },
    htdy: { seriesKind: 'continuous' as const, frequency: '60m' as const },
    free: { seriesKind: 'actual_dominant' as const, frequency: '5m' as const },
  }
  assert.deepEqual(resolveViewSwitchIdentity('newow', 'rb', null, restore), {
    view: 'newow', symbol: 'rb', strategy: 'main_rise', seriesKind: 'actual_dominant', frequency: '1w',
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

 test('migration preserves physical identities and HTDY focus, rejects malformed and conflicting fields', () => {
  for (const overlay of [undefined, 'none', 'htdy']) {
    const view = overlay === 'htdy' ? 'htdy' : 'free'
    const query = { symbol: 'jm', series_kind: 'contract', contract: 'JM2601', frequency: '60m', overlay }
    assert.deepEqual(parseMarketDetailRoute(query), { kind: 'valid', identity: { view, symbol: 'jm', seriesKind: 'contract', contract: 'JM2601', frequency: '60m' } })
    const focus = { symbol: 'jm', series_kind: 'actual_dominant', frequency: '15m', overlay, focus_bar_end: '2026-09-02T02:45:00Z' }
    const parsed = parseMarketDetailRoute(focus)
    assert.equal(parsed.kind, 'valid')
    if (parsed.kind === 'valid') assert.equal(parsed.identity.focusBarEnd, focus.focus_bar_end)
  }
  for (const query of [
    { symbol: 'jm', overlay: 'unknown' }, { symbol: 'jm', view: ['free'] },
    { symbol: 'jm', contract: ['JM2601'] }, { symbol: 'jm', frequency: ['15m'] },
    { symbol: 'jm', series_kind: 'contract', contract: 'RB2601' },
    { symbol: 'jm', view: 'newow', overlay: 'htdy' },
  ]) assert.equal(parseMarketDetailRoute(query).kind, 'invalid')
})


test('only Newow strategy changes preserve the price shell', async () => {
  const { isNewowStrategySwitch } = await import('../src/utils/marketDetailRoute.ts')
  const previous = { view: 'newow', symbol: 'jm', strategy: 'trend', frequency: '1d', seriesKind: 'actual_dominant' } as const
  for (const strategy of ['oscillation', 'main_rise'] as const) {
    assert.equal(isNewowStrategySwitch(previous, { ...previous, strategy }), true)
    assert.equal(isNewowStrategySwitch({ ...previous, strategy }, previous), true)
  }
  assert.equal(isNewowStrategySwitch(previous, previous), false)
  assert.equal(isNewowStrategySwitch(null, previous), false)
  assert.equal(isNewowStrategySwitch(previous, { ...previous, strategy: 'oscillation', symbol: 'rb' }), false)
  assert.equal(isNewowStrategySwitch(previous, { ...previous, strategy: 'oscillation', frequency: '1w' }), false)
  assert.equal(isNewowStrategySwitch(previous, { ...previous, view: 'free', strategy: undefined }), false)
})


test('dual presentation roundtrips without inventing a fourth strategy kernel', () => {
  const identity = { view: 'newow' as const, symbol: 'jm', strategy: 'trend' as const,
    newowMode: 'dual' as const, seriesKind: 'actual_dominant' as const, frequency: '1w' as const }
  assert.deepEqual(parseMarketDetailRoute(serializeMarketDetailIdentity(identity)), { kind: 'valid', identity })
  assert.equal(isNewowStrategySwitch({ ...identity, newowMode: undefined }, identity), true)
  assert.equal(isNewowStrategySwitch(identity, { ...identity, newowMode: undefined }), true)
  assert.equal(isNewowStrategySwitch(identity, { ...identity, symbol: 'rb' }), false)
  for (const query of [
    { view: 'newow', strategy: 'main_rise', newow_mode: 'dual' },
    { view: 'newow', strategy: 'oscillation', newow_mode: 'dual' },
    { view: 'newow', strategy: 'trend', newow_mode: 'fusion' },
    { view: 'free', newow_mode: 'dual', frequency: '1d', series_kind: 'actual_dominant' },
  ]) assert.equal(parseMarketDetailRoute({ symbol: 'jm', ...query }).kind, 'invalid')
  assert.equal(parseMarketDetailRoute({ view: 'newow', symbol: 'jm', strategy: 'main_rise' }).kind, 'valid')
})
