import assert from 'node:assert/strict'
import test from 'node:test'
import { nextTick, ref } from 'vue'

import { NewowTrendDetailRequestError } from '../src/api/newow.ts'
import { useNewowTrendDetail } from '../src/composables/useNewowTrendDetail.ts'
import type { NewowTrendDetailResponse } from '../src/types/newow.ts'
import { normalizeNewowTrendDetailResponse } from '../src/utils/newowTypes.ts'
import type { BarData } from '../src/types/market.ts'
import type { MarketDetailIdentity } from '../src/types/marketDetail.ts'

test('derives the request window only from ordered generic D1 trading days', async () => {
  const calls: Array<{ product: string; from: string; through: string; signal: AbortSignal }> = []
  const state = useNewowTrendDetail({
    identity: ref(trendIdentity('jm')),
    bars: ref(bars('2026-08-14', '2026-08-15')),
    fetchDetail: async (params, signal) => {
      calls.push({ ...params, signal })
      return normalizedEmpty(params.product, params.from, params.through)
    },
  })
  await flush()

  assert.deepEqual(calls.map(({ signal: _signal, ...params }) => params), [{
    product: 'jm', from: '2026-08-14', through: '2026-08-15',
  }])
  assert.equal(calls[0]!.signal.aborted, false)
  assert.equal(state.loading.value, false)
  assert.equal(state.error.value, null)
  assert.equal(state.data.value?.instrument.product, 'jm')
  state.dispose()
})

test('rejects empty, malformed, duplicate, and unordered generic windows without a request', async () => {
  const invalidWindows: BarData[][] = [
    [],
    [{ ...bar('2026-08-14'), trading_day: undefined }],
    bars('2026-08-14', '2026-08-14'),
    bars('2026-08-15', '2026-08-14'),
    bars('2026-02-30'),
  ]
  for (const invalid of invalidWindows) {
    let calls = 0
    const state = useNewowTrendDetail({
      identity: ref(trendIdentity('jm')),
      bars: ref(invalid),
      fetchDetail: async () => {
        calls += 1
        return normalizedEmpty('jm', '2026-08-14', '2026-08-15')
      },
    })
    await flush()
    assert.equal(calls, 0)
    assert.equal(state.loading.value, false)
    assert.equal(state.data.value, null)
    assert.equal(state.error.value, 'NEWOW_WINDOW_INVALID')
    state.dispose()
  }
})

test('aborts a replaced generation, clears prior data, and accepts only the latest valid response', async () => {
  const identity = ref<MarketDetailIdentity | null>(trendIdentity('jm'))
  const genericBars = ref(bars('2026-08-14', '2026-08-15'))
  const pending: Array<{
    product: string
    signal: AbortSignal
    resolve: (value: NewowTrendDetailResponse) => void
  }> = []
  const state = useNewowTrendDetail({
    identity,
    bars: genericBars,
    fetchDetail: (params, signal) => new Promise((resolve) => {
      pending.push({ product: params.product, signal, resolve })
    }),
  })
  await nextTick()
  pending[0]!.resolve(normalizedEmpty('jm', '2026-08-14', '2026-08-15'))
  await flush()
  assert.equal(state.data.value?.instrument.product, 'jm')

  genericBars.value = bars('2026-08-14', '2026-08-18')
  await nextTick()
  assert.equal(state.data.value, null)
  assert.equal(state.loading.value, true)

  identity.value = trendIdentity('ag')
  genericBars.value = bars('2026-08-18', '2026-08-19')
  await nextTick()
  assert.equal(pending[1]!.signal.aborted, true)
  assert.equal(state.data.value, null)
  assert.equal(state.loading.value, true)
  assert.equal(state.error.value, null)

  const latest = pending.at(-1)!
  latest.resolve(normalizedEmpty('ag', '2026-08-18', '2026-08-19'))
  await flush()
  assert.equal(state.data.value?.instrument.product, 'ag')

  // A transport that ignores abort still cannot overwrite the final generation.
  const stale = pending[1]!
  stale.resolve(normalizedEmpty('jm', '2026-08-14', '2026-08-18'))
  await flush()
  assert.equal(state.data.value?.instrument.product, 'ag')
  state.dispose()
})

test('publishes safe API, response, and allowlisted service errors with no stale snapshot', async () => {
  const codes = [
    'NEWOW_API_UNAVAILABLE',
    'NEWOW_RESPONSE_INVALID',
    'NEWOW_INVALID_RANGE',
    'NEWOW_DATA_UNAVAILABLE',
  ] as const
  for (const code of codes) {
    const state = useNewowTrendDetail({
      identity: ref(trendIdentity('jm')),
      bars: ref(bars('2026-08-14')),
      fetchDetail: async () => { throw new NewowTrendDetailRequestError(code) },
    })
    await flush()
    assert.equal(state.loading.value, false)
    assert.equal(state.data.value, null)
    assert.equal(state.error.value, code)
    state.dispose()
  }
})

test('dispose aborts the active request and invalidates a late response', async () => {
  let activeSignal: AbortSignal | null = null
  let resolveRequest!: (value: NewowTrendDetailResponse) => void
  const state = useNewowTrendDetail({
    identity: ref(trendIdentity('jm')),
    bars: ref(bars('2026-08-14')),
    fetchDetail: (_params, signal) => {
      activeSignal = signal
      return new Promise((resolve) => { resolveRequest = resolve })
    },
  })
  await nextTick()
  state.dispose()
  assert.equal(activeSignal?.aborted, true)
  resolveRequest(normalizedEmpty('jm', '2026-08-14', '2026-08-14'))
  await flush()
  assert.equal(state.loading.value, false)
  assert.equal(state.data.value, null)
  assert.equal(state.error.value, null)
})

function trendIdentity(symbol: string): MarketDetailIdentity {
  return { view: 'trend', symbol, seriesKind: 'actual_dominant', frequency: '1d' }
}

function bars(...days: string[]): BarData[] {
  return days.map(bar)
}

function bar(tradingDay: string): BarData {
  return {
    time: `${tradingDay}T15:00:00+08:00`,
    trading_day: tradingDay,
    open: 100,
    high: 101,
    low: 99,
    close: 100,
    volume: 1,
  }
}

function normalizedEmpty(product: string, from: string, through: string): NewowTrendDetailResponse {
  const calculation = [
    'market_data_service:canonical_v2',
    'main_contract_map:rank1:canonical_v1',
    product,
    'actual_dominant',
    '1d',
    'newow_trend_d1_v1',
    'newow_trend_band_cleanroom_v1',
    'newow_escape_d123_v1',
    'newow_cup_handle_v1',
  ].join('|')
  return normalizeNewowTrendDetailResponse({
    meta: {
      strategy_code: 'newow_trend_v1', profile_id: 'newow_trend_d1_v1', frequency: '1d',
      series_kind: 'actual_dominant', calculation_identity: calculation, data_revision_identity: null,
      request_identity: `${calculation}:${from}:${through}`,
    },
    instrument: { product, display_name: null, last_visible_physical_contract: null },
    bars: [],
    bar_policy: 'completed_only',
    trend_band: [], trend_markers: [], escape_markers: [], cup_markers: [], cup_handles: [], rollover_seams: [],
    legend: { BUILD: 'trend build', CLEAR: 'trend clear', D1: 'escape D1', D2: 'escape D2', D3: 'escape D3' },
    formula_descriptions: {
      trend_band: 'newow_trend_band_cleanroom_v1', escape: 'newow_escape_d123_v1', cup_handle: 'newow_cup_handle_v1',
    },
    warnings: [
      'NEWOW_TREND_WARMUP_INSUFFICIENT',
      'NEWOW_D123_WARMUP_INSUFFICIENT',
      'NEWOW_CUP_WARMUP_INSUFFICIENT',
    ],
  }, { symbol: product, from, through })
}

async function flush(): Promise<void> {
  await nextTick()
  await Promise.resolve()
  await Promise.resolve()
}
