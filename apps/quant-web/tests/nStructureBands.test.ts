import test from 'node:test'
import assert from 'node:assert/strict'
import type {
  BarData,
  MarketBarsPageResponse,
  NStructureBandRequest,
  NStructureBandResponse,
} from '../src/types/market.ts'
import { useNStructureBands } from '../src/composables/useNStructureBands.ts'

const coverage: MarketBarsPageResponse['canonical_coverage'] = {
  start: '2026-08-20T01:00:00Z',
  end: '2026-08-22T01:00:00Z',
}
const bars: BarData[] = [
  bar('2026-08-20T01:00:00Z', '2026-08-20'),
  bar('2026-08-21T01:00:00Z', '2026-08-21'),
  bar('2026-08-22T01:00:00Z', '2026-08-22'),
]

test('N structure bands load only for enabled actual-dominant 5m and validate lineage', async () => {
  const requests: NStructureBandRequest[] = []
  const state = useNStructureBands({
    fetchBands: async (request) => {
      requests.push(request)
      return response(request, [band('b-1', '2026-08-21T01:00:00Z')])
    },
  })

  await state.sync(identity(false), bars, coverage, 'replace')
  await state.sync({ ...identity(true), frequency: '15m' }, bars, coverage, 'replace')
  assert.equal(requests.length, 0)
  assert.deepEqual(state.bands.value, [])

  await state.sync(identity(true), bars, coverage, 'replace')
  assert.deepEqual(requests, [{
    series_kind: 'actual_dominant',
    symbol: 'au',
    frequency: '5m',
    since: '2026-08-20',
    through: '2026-08-22',
  }])
  assert.deepEqual(state.bands.value.map((item) => item.band_id), ['b-1'])
  assert.equal(state.error.value, null)
})

test('prepend requests only the added date window and deduplicates by band id', async () => {
  const requests: NStructureBandRequest[] = []
  const state = useNStructureBands({
    fetchBands: async (request) => {
      requests.push(request)
      return response(request, request.since === '2026-08-18'
        ? [
            band('b-0', '2026-08-19T01:00:00Z', { expandedUntil: '2026-08-21T01:00:00Z' }),
            band('b-1', '2026-08-21T01:00:00Z', { expandedUntil: '2026-08-21T01:00:00Z' }),
          ]
        : [band('b-1', '2026-08-21T01:00:00Z', {
            firstReenteredAt: '2026-08-21T12:00:00Z',
            expandedUntil: '2026-08-22T01:00:00Z',
          })])
    },
  })
  await state.sync(identity(true), bars.slice(1), coverage, 'replace')
  const prepended = [bar('2026-08-18T01:00:00Z', '2026-08-18'), ...bars]
  await state.sync(identity(true), prepended, {
    start: '2026-08-18T01:00:00Z',
    end: coverage.end,
  }, 'prepend')

  assert.deepEqual(requests.map((item) => [item.since, item.through]), [
    ['2026-08-21', '2026-08-22'],
    ['2026-08-18', '2026-08-21'],
  ])
  assert.deepEqual(state.bands.value.map((item) => item.band_id), ['b-0', 'b-1'])
  assert.equal(state.bands.value[1]?.expanded_until, '2026-08-22T01:00:00Z')
  assert.equal(state.bands.value[1]?.first_reentered_at, '2026-08-21T12:00:00Z')
})

test('a current prepend failure clears the incomplete band layer and keeps K-line ownership external', async () => {
  let calls = 0
  const state = useNStructureBands({
    fetchBands: async (request) => {
      calls += 1
      if (calls === 1) return response(request, [band('b-1', '2026-08-21T01:00:00Z')])
      throw new Error('prepend unavailable')
    },
  })
  await state.sync(identity(true), bars.slice(1), coverage, 'replace')
  assert.deepEqual(state.bands.value.map((item) => item.band_id), ['b-1'])

  await state.sync(identity(true), [bar('2026-08-18T01:00:00Z', '2026-08-18'), ...bars], {
    start: '2026-08-18T01:00:00Z',
    end: coverage.end,
  }, 'prepend')

  assert.deepEqual(state.bands.value, [])
  assert.equal(state.error.value, 'N_STRUCTURE_BANDS_UNAVAILABLE')
})

test('live mutation never computes and unsupported identity clears visible bands', async () => {
  let calls = 0
  const state = useNStructureBands({
    fetchBands: async (request) => {
      calls += 1
      return response(request, [band('b-1', '2026-08-21T01:00:00Z')])
    },
  })
  await state.sync(identity(true), bars, coverage, 'replace')
  await state.sync(identity(true), bars, coverage, 'live')
  assert.equal(calls, 1)
  assert.equal(state.bands.value.length, 1)

  await state.sync({ ...identity(true), seriesKind: 'continuous' }, bars, coverage, 'replace')
  assert.deepEqual(state.bands.value, [])
  assert.equal(calls, 1)
})

test('stale response is discarded and current failure stays non-blocking', async () => {
  let resolveFirst!: (value: NStructureBandResponse) => void
  const first = new Promise<NStructureBandResponse>((resolve) => { resolveFirst = resolve })
  let calls = 0
  const state = useNStructureBands({
    fetchBands: async (request) => {
      calls += 1
      if (calls === 1) return first
      throw new Error(`unavailable:${request.symbol}`)
    },
  })
  const pending = state.sync(identity(true), bars, coverage, 'replace')
  const changed = { ...identity(true), symbol: 'ag' }
  await state.sync(changed, bars, coverage, 'replace')
  assert.equal(state.error.value, 'N_STRUCTURE_BANDS_UNAVAILABLE')
  resolveFirst(response({
    series_kind: 'actual_dominant',
    symbol: 'au',
    frequency: '5m',
    since: '2026-08-20',
    through: '2026-08-22',
  }, [band('stale', '2026-08-21T01:00:00Z')]))
  await pending
  assert.deepEqual(state.bands.value, [])
  assert.equal(state.loading.value, false)
})

test('response identity or policy mismatch is rejected', async () => {
  const state = useNStructureBands({
    fetchBands: async (request) => ({
      ...response(request, []),
      policy: {
        policy_id: 'wrong',
        formula_version: 'n_structure_v1',
        source_timeframe: '5m',
        research_only: true,
      },
    }),
  })
  await state.sync(identity(true), bars, coverage, 'replace')
  assert.equal(state.error.value, 'N_STRUCTURE_BANDS_UNAVAILABLE')
  assert.deepEqual(state.bands.value, [])
})

test('a missing lifecycle timestamp fails closed instead of drawing invalid coordinates', async () => {
  const state = useNStructureBands({
    fetchBands: async (request) => response(request, [{
      ...band('legacy', '2026-08-21T01:00:00Z'),
      expanded_until: undefined,
    // The cast models an older server payload crossing the runtime boundary.
    } as unknown as ReturnType<typeof band>]),
  })

  await state.sync(identity(true), bars, coverage, 'replace')

  assert.equal(state.error.value, 'N_STRUCTURE_BANDS_UNAVAILABLE')
  assert.deepEqual(state.bands.value, [])
})

test('prepend rejects a duplicate band id with contradictory immutable facts', async () => {
  let calls = 0
  const original = band('conflict', '2026-08-21T01:00:00Z', {
    expandedUntil: '2026-08-22T01:00:00Z',
  })
  const state = useNStructureBands({
    fetchBands: async (request) => {
      calls += 1
      return response(request, calls === 1 ? [original] : [{ ...original, lower: 97 }])
    },
  })

  await state.sync(identity(true), bars.slice(1), coverage, 'replace')
  await state.sync(identity(true), [bar('2026-08-18T01:00:00Z', '2026-08-18'), ...bars], {
    start: '2026-08-18T01:00:00Z',
    end: coverage.end,
  }, 'prepend')

  assert.equal(state.error.value, 'N_STRUCTURE_BANDS_UNAVAILABLE')
  assert.deepEqual(state.bands.value, [])
})

test('prepend rejects lifecycle facts that become contradictory after merge', async () => {
  let calls = 0
  const current = band('lifecycle-conflict', '2026-08-20T01:00:00Z', {
    firstReenteredAt: '2026-08-22T01:00:00Z',
    expandedUntil: '2026-08-23T01:00:00Z',
  })
  const earlier = band('lifecycle-conflict', '2026-08-20T01:00:00Z', {
    invalidatedAt: '2026-08-21T01:00:00Z',
    expandedUntil: '2026-08-21T01:00:00Z',
  })
  const state = useNStructureBands({
    fetchBands: async (request) => {
      calls += 1
      return response(request, calls === 1 ? [current] : [earlier])
    },
  })

  await state.sync(identity(true), bars.slice(1), coverage, 'replace')
  await state.sync(identity(true), [bar('2026-08-18T01:00:00Z', '2026-08-18'), ...bars], {
    start: '2026-08-18T01:00:00Z',
    end: coverage.end,
  }, 'prepend')

  assert.equal(state.error.value, 'N_STRUCTURE_BANDS_UNAVAILABLE')
  assert.deepEqual(state.bands.value, [])
})

test('direction-role and trading-day lineage mismatches fail closed at the HTTP boundary', async () => {
  const valid = band('lineage', '2026-08-21T01:00:00Z')
  const malformed = [
    { ...valid, role: 'resistance_reference' as const },
    { ...valid, segment_start_trading_day: '2026/08/01' },
    { ...valid, completion_trading_day: '2026-07-31' },
  ]

  for (const item of malformed) {
    const state = useNStructureBands({
      fetchBands: async (request) => response(request, [item]),
    })
    await state.sync(identity(true), bars, coverage, 'replace')
    assert.equal(state.error.value, 'N_STRUCTURE_BANDS_UNAVAILABLE')
    assert.deepEqual(state.bands.value, [])
  }
})

function identity(enabled: boolean) {
  return {
    enabled,
    seriesKind: 'actual_dominant' as const,
    symbol: 'au',
    frequency: '5m' as const,
  }
}

function bar(time: string, tradingDay: string): BarData {
  return { time, trading_day: tradingDay, open: 100, high: 102, low: 98, close: 101, volume: 10 }
}

function band(
  bandId: string,
  completedAt: string,
  lifecycle: {
    firstReenteredAt?: string | null
    invalidatedAt?: string | null
    expandedUntil?: string
  } = {},
) {
  return {
    band_id: bandId,
    contract: 'AU2610',
    segment_start_trading_day: '2026-08-01',
    completion_trading_day: completedAt.slice(0, 10),
    direction: 'up' as const,
    role: 'support_reference' as const,
    n1_at: new Date(Date.parse(completedAt) - 3_600_000).toISOString(),
    completed_at: completedAt,
    completion_level: 101,
    lower: 98,
    upper: 102,
    first_reentered_at: lifecycle.firstReenteredAt ?? null,
    invalidated_at: lifecycle.invalidatedAt ?? null,
    expanded_until: lifecycle.expandedUntil ?? completedAt,
  }
}

function response(request: NStructureBandRequest, items: ReturnType<typeof band>[]): NStructureBandResponse {
  return {
    request,
    policy: {
      policy_id: 'n_structure_5m_v1',
      formula_version: 'n_structure_v1',
      source_timeframe: '5m',
      research_only: true,
    },
    bands: items,
  }
}
