import assert from 'node:assert/strict'
import { describe, it } from 'node:test'

import { useMainForceMirrorV2 } from '../src/composables/useMainForceMirrorV2.ts'
import type {
  MainForceMirrorV2Identity,
  MainForceMirrorV2PageRequest,
  MainForceMirrorV2PageResponse,
  MainForceMirrorV2PageWireResponse,
} from '../src/types/market.ts'
import { normalizeMainForceMirrorV2Page } from '../src/types/market.ts'
import {
  buildMainForceMirrorV2RenderModel,
  normalizeSecondaryPanelPreference,
} from '../src/utils/mainForceMirrorV2Presentation.ts'

function identity(symbol = 'jm'): MainForceMirrorV2Identity {
  return {
    seriesKind: 'actual_dominant',
    symbol,
    frequency: '60m',
  }
}

function mirrorPage(overrides: Partial<MainForceMirrorV2PageWireResponse> = {}): MainForceMirrorV2PageWireResponse {
  const request = overrides.request ?? {
    series_kind: 'actual_dominant',
    symbol: 'jm',
    contract: null,
    frequency: '60m',
    before: null,
    limit: 1200,
  }
  return {
    request,
    indicator: {
      indicator_code: 'main_force_mirror_v2',
      indicator_version: 'futures-member-research-v2',
      formal_policy_id: 'main_force_mirror_observation_v2',
      parameters_hash: 'frozen-parameters',
      interpretation: 'directional_position_pressure_proxy_not_measured_fund_flow',
      observation_only: true,
      historical_only: true,
      auto_order: false,
    },
    member_dataset: {
      status: 'ready',
      dataset_id: 'member-rank-v1',
      schema_version: 1,
      admitted_product: true,
      coverage: { start: '2026-01-01', end: '2026-08-20' },
    },
    points: [wirePoint('2026-08-20T02:30:00Z')],
    page: { has_more_before: false, next_before: null },
    resolved_contract_segments: [{
      contract: 'JM2609',
      start_trading_day: '2026-08-01',
      end_trading_day: '2026-08-20',
    }],
    ...overrides,
  }
}

function wirePoint(barEnd: string, overrides: Partial<MainForceMirrorV2PageWireResponse['points'][number]> = {}) {
  return {
    bar_end: barEnd,
    trading_day: barEnd.slice(0, 10),
    physical_contract: 'JM2609',
    pressure_ready: true,
    pressure_state: 'long_build' as const,
    instant_pressure: 36.2,
    accumulated_ready: true,
    accumulated_pressure: 15.5,
    caution_ready: true,
    caution: 'long_chase_caution' as const,
    caution_conflict: false,
    long_caution_score: 72,
    short_caution_score: 4,
    caution_reason_codes: ['LONG_UPPER_EXTREME'],
    price_impulse: 0.1234,
    clv: -0.3,
    volume_ratio: 1.5,
    delta_oi: 320,
    oi_impulse: 0.456,
    range_position: 0.8,
    member_status: 'ready' as const,
    member_trade_date: '2026-08-19',
    member_direction: 'long' as const,
    member_change_bias: 0.2,
    member_strength: 2.1,
    position_skew: 0.6,
    top5_volume_share: 0.4,
    relation_to_accumulated: 'strong_aligned' as const,
    relation_to_caution: 'aligned' as const,
    unavailable_reason: null,
    ...overrides,
  }
}

function normalizedPage(overrides: Partial<MainForceMirrorV2PageWireResponse> = {}): MainForceMirrorV2PageResponse {
  return normalizeMainForceMirrorV2Page(mirrorPage(overrides))
}

type UnknownRecord = Record<string, unknown>

function malformedPage(mutate: (page: UnknownRecord) => void): MainForceMirrorV2PageWireResponse {
  const page = mirrorPage() as unknown as UnknownRecord
  mutate(page)
  return page as unknown as MainForceMirrorV2PageWireResponse
}

function nested(page: UnknownRecord, key: string): UnknownRecord {
  return page[key] as UnknownRecord
}

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason?: unknown) => void
  const promise = new Promise<T>((nextResolve, nextReject) => {
    resolve = nextResolve
    reject = nextReject
  })
  return { promise, resolve, reject }
}

describe('main force mirror v2 HTTP normalization', () => {
  it('accepts every numeric V2 API value once at the HTTP boundary and normalizes negative zero', () => {
    const result = normalizeMainForceMirrorV2Page(mirrorPage())
    const point = result.points[0]

    assert.equal(point.instant_pressure, 36.2)
    assert.equal(point.accumulated_pressure, 15.5)
    assert.equal(point.long_caution_score, 72)
    assert.equal(point.short_caution_score, 4)
    assert.equal(point.price_impulse, 0.1234)
    assert.equal(point.clv, -0.3)
    assert.equal(point.volume_ratio, 1.5)
    assert.equal(point.delta_oi, 320)
    assert.equal(point.oi_impulse, 0.456)
    assert.equal(point.range_position, 0.8)
    assert.equal(point.member_change_bias, 0.2)
    assert.equal(point.member_strength, 2.1)
    assert.equal(point.position_skew, 0.6)
    assert.equal(point.top5_volume_share, 0.4)
    assert.equal(point.caution_conflict, false)
    const negativeZero = normalizeMainForceMirrorV2Page(mirrorPage({
      points: [wirePoint('2026-08-20T02:30:00Z', { member_strength: -0 })],
    }))
    assert.equal(Object.is(negativeZero.points[0].member_strength, -0), false)
  })

  it('rejects non-finite numeric values and string transport values', () => {
    const nonFinite = mirrorPage({
      points: [wirePoint('2026-08-20T02:30:00Z', { instant_pressure: Infinity })],
    })
    const stringTransport = mirrorPage({
      points: [wirePoint('2026-08-20T02:30:00Z', { instant_pressure: '36.2' as never })],
    })

    assert.throws(() => normalizeMainForceMirrorV2Page(nonFinite))
    assert.throws(() => normalizeMainForceMirrorV2Page(stringTransport))
  })

  it('rejects malformed page shapes before they enter V2 state', () => {
    assert.throws(() => normalizeMainForceMirrorV2Page({
      ...mirrorPage(),
      page: null as never,
    }))
  })

  it('rejects every malformed non-numeric Task 5 nested response field', () => {
    const malformed: Array<[string, (page: UnknownRecord) => void]> = [
      ['page cursor fields', (page) => {
        const value = nested(page, 'page')
        value.has_more_before = 'yes'
        value.next_before = 1
      }],
      ['request series kind', (page) => { nested(page, 'request').series_kind = 'continuous' }],
      ['request symbol', (page) => { nested(page, 'request').symbol = 1 }],
      ['request contract', (page) => { nested(page, 'request').contract = 1 }],
      ['request frequency', (page) => { nested(page, 'request').frequency = '15m' }],
      ['request before', (page) => { nested(page, 'request').before = 1 }],
      ['request limit', (page) => { nested(page, 'request').limit = 1.5 }],
      ['indicator identity', (page) => { nested(page, 'indicator').indicator_code = 'other' }],
      ['indicator version', (page) => { nested(page, 'indicator').indicator_version = 'other' }],
      ['indicator policy', (page) => { nested(page, 'indicator').formal_policy_id = 'other' }],
      ['indicator hash', (page) => { nested(page, 'indicator').parameters_hash = 1 }],
      ['indicator interpretation', (page) => { nested(page, 'indicator').interpretation = 'other' }],
      ['indicator observation flag', (page) => { nested(page, 'indicator').observation_only = false }],
      ['indicator historical flag', (page) => { nested(page, 'indicator').historical_only = false }],
      ['indicator order flag', (page) => { nested(page, 'indicator').auto_order = true }],
      ['member dataset status', (page) => { nested(page, 'member_dataset').status = 'other' }],
      ['member dataset id', (page) => { nested(page, 'member_dataset').dataset_id = 1 }],
      ['member dataset schema', (page) => { nested(page, 'member_dataset').schema_version = 1.5 }],
      ['member dataset admission', (page) => { nested(page, 'member_dataset').admitted_product = 'yes' }],
      ['member dataset coverage', (page) => { nested(nested(page, 'member_dataset'), 'coverage').start = 1 }],
      ['resolved contract segment', (page) => { (page.resolved_contract_segments as UnknownRecord[])[0].contract = '' }],
      ['point timestamp', (page) => { (page.points as UnknownRecord[])[0].bar_end = '2026-08-20' }],
      ['point trading day', (page) => { (page.points as UnknownRecord[])[0].trading_day = 1 }],
      ['point contract', (page) => { (page.points as UnknownRecord[])[0].physical_contract = '' }],
      ['point readiness', (page) => { (page.points as UnknownRecord[])[0].pressure_ready = 'yes' }],
      ['point pressure state', (page) => { (page.points as UnknownRecord[])[0].pressure_state = 'other' }],
      ['point caution state', (page) => { (page.points as UnknownRecord[])[0].caution = 'other' }],
      ['point reason codes', (page) => { (page.points as UnknownRecord[])[0].caution_reason_codes = [1] }],
      ['point member status', (page) => { (page.points as UnknownRecord[])[0].member_status = 'other' }],
      ['point member date', (page) => { (page.points as UnknownRecord[])[0].member_trade_date = 'not-a-date' }],
      ['point member direction', (page) => { (page.points as UnknownRecord[])[0].member_direction = 'other' }],
      ['point relations', (page) => { (page.points as UnknownRecord[])[0].relation_to_accumulated = 'other' }],
      ['point unavailable reason', (page) => { (page.points as UnknownRecord[])[0].unavailable_reason = 1 }],
    ]

    for (const [name, mutate] of malformed) {
      assert.throws(() => normalizeMainForceMirrorV2Page(malformedPage(mutate)), undefined, name)
    }
  })
})

describe('main force mirror v2 presentation', () => {
  it('projects instant bars, accumulated EMA5 and caution labels without recomputing server values', () => {
    const first = normalizeMainForceMirrorV2Page(mirrorPage({
      points: [wirePoint('2026-08-21T02:00:00Z', {
        instant_pressure: 36.2,
        accumulated_pressure: 18.7,
        caution: null,
        long_caution_score: null,
      })],
    })).points[0]
    const second = normalizeMainForceMirrorV2Page(mirrorPage({
      points: [wirePoint('2026-08-21T03:00:00Z', {
        instant_pressure: null,
        accumulated_pressure: null,
        caution: 'long_chase_caution',
        long_caution_score: 70,
        relation_to_caution: 'strong_aligned',
      })],
    })).points[0]

    const model = buildMainForceMirrorV2RenderModel([first, second])

    assert.deepEqual(model.histogram[0].value, 36.2)
    assert.deepEqual(model.accumulated[0].value, 18.7)
    assert.equal(model.markers[0].text, '追多小心 70｜席位强同向')
    assert.equal(model.latest, second)
    assert.deepEqual(model.autoscale, { minValue: -105, maxValue: 105 })
  })

  it('keeps a caution marker and explicit relation when member data is unavailable', () => {
    const point = normalizeMainForceMirrorV2Page(mirrorPage({
      points: [wirePoint('2026-08-21T03:00:00Z', {
        caution: 'short_chase_caution',
        short_caution_score: null,
        member_status: 'unavailable',
        member_trade_date: null,
        member_direction: null,
        member_change_bias: null,
        member_strength: null,
        position_skew: null,
        top5_volume_share: null,
        relation_to_accumulated: 'unavailable',
        relation_to_caution: 'unavailable',
        unavailable_reason: 'MFM_MEMBER_SNAPSHOT_MISSING',
      })],
    })).points[0]

    const model = buildMainForceMirrorV2RenderModel([point])

    assert.equal(model.markers.length, 1)
    assert.match(model.markers[0].text, /追空小心 —｜席位不可用/)
  })

  it('keeps only the active V2 secondary pane and defaults every other value to MACD', () => {
    assert.equal(normalizeSecondaryPanelPreference('main_force_mirror_v2'), 'main_force_mirror_v2')
    assert.equal(normalizeSecondaryPanelPreference('unknown'), 'macd')
    assert.equal(normalizeSecondaryPanelPreference(null), 'macd')
  })
})

describe('main force mirror v2 page state', () => {
  it('clears every old V2 value immediately before a replacement resolves', async () => {
    const pending = deferred<MainForceMirrorV2PageResponse>()
    let calls = 0
    const mirror = useMainForceMirrorV2({
      fetchPage: () => {
        calls += 1
        return calls === 1 ? Promise.resolve(normalizedPage({
          page: { has_more_before: true, next_before: '2026-08-20T02:30:00Z' },
        })) : pending.promise
      },
    })

    await mirror.replace(identity())
    assert.equal(mirror.points.value.length, 1)
    assert.equal(mirror.memberDataset.value?.dataset_id, 'member-rank-v1')
    assert.equal(mirror.canonicalEnd.value, '2026-08-20T02:30:00Z')

    const replacing = mirror.replace(identity('ag'))
    assert.deepEqual(mirror.points.value, [])
    assert.equal(mirror.memberDataset.value, null)
    assert.equal(mirror.canonicalEnd.value, null)
    assert.equal(mirror.nextBefore.value, null)
    assert.equal(mirror.hasMoreBefore.value, false)
    assert.equal(mirror.error.value, null)

    pending.resolve(normalizedPage({
      request: { ...mirrorPage().request, symbol: 'ag' },
    }))
    await replacing
    assert.equal(mirror.memberDataset.value?.dataset_id, 'member-rank-v1')
    assert.equal(mirror.canonicalEnd.value, '2026-08-20T02:30:00Z')
  })

  it('drops an older identity response after clear', async () => {
    const pending = deferred<MainForceMirrorV2PageResponse>()
    let calls = 0
    const mirror = useMainForceMirrorV2({
      fetchPage: () => {
        calls += 1
        return calls === 1 ? Promise.resolve(normalizedPage({
          page: { has_more_before: true, next_before: '2026-08-20T02:30:00Z' },
        })) : pending.promise
      },
    })
    await mirror.replace(identity())
    const oldRequest = mirror.loadMoreBefore()

    mirror.clear()
    pending.resolve(normalizedPage())
    await oldRequest

    assert.deepEqual(mirror.points.value, [])
    assert.equal(mirror.memberDataset.value, null)
    assert.equal(mirror.canonicalEnd.value, null)
    assert.equal(mirror.loading.value, false)
  })

  it('does not let a stale replacement error or finally change the next identity', async () => {
    const ag = deferred<MainForceMirrorV2PageResponse>()
    const jm = deferred<MainForceMirrorV2PageResponse>()
    const mirror = useMainForceMirrorV2({
      fetchPage: (request) => request.symbol === 'ag' ? ag.promise : jm.promise,
    })

    const oldRequest = mirror.replace(identity('ag'))
    const newRequest = mirror.replace(identity('jm'))
    jm.resolve(normalizedPage())
    await newRequest
    ag.reject(new Error('sensitive backend detail'))
    await oldRequest

    assert.deepEqual(mirror.points.value.map((point) => point.bar_end), ['2026-08-20T02:30:00Z'])
    assert.equal(mirror.error.value, null)
    assert.equal(mirror.loading.value, false)
    assert.equal(mirror.memberDataset.value?.dataset_id, 'member-rank-v1')
  })

  it('does not let a stale replacement response overwrite the newer identity', async () => {
    const ag = deferred<MainForceMirrorV2PageResponse>()
    const jm = deferred<MainForceMirrorV2PageResponse>()
    const mirror = useMainForceMirrorV2({
      fetchPage: (request) => request.symbol === 'ag' ? ag.promise : jm.promise,
    })

    const oldRequest = mirror.replace(identity('ag'))
    const newRequest = mirror.replace(identity('jm'))
    jm.resolve(normalizedPage())
    await newRequest
    ag.resolve(normalizedPage({ request: { ...mirrorPage().request, symbol: 'ag' } }))
    await oldRequest

    assert.deepEqual(mirror.points.value.map((point) => point.bar_end), ['2026-08-20T02:30:00Z'])
    assert.equal(mirror.error.value, null)
    assert.equal(mirror.loading.value, false)
  })

  it('clears V2 state and exposes only a safe message when a request fails', async () => {
    const mirror = useMainForceMirrorV2({
      fetchPage: async () => { throw new Error('/private/member-snapshot.parquet') },
    })

    await mirror.replace(identity())

    assert.deepEqual(mirror.points.value, [])
    assert.equal(mirror.memberDataset.value, null)
    assert.equal(mirror.canonicalEnd.value, null)
    assert.equal(mirror.error.value, '主力照妖镜 V2 暂不可用')
  })

  it('clears V2 state when HTTP normalization rejects an invalid numeric response', async () => {
    let calls = 0
    const mirror = useMainForceMirrorV2({
      fetchPage: async () => {
        calls += 1
        return calls === 1
          ? normalizedPage()
          : normalizeMainForceMirrorV2Page(mirrorPage({
              request: { ...mirrorPage().request, symbol: 'ag' },
              points: [wirePoint('2026-08-20T02:30:00Z', { instant_pressure: Infinity })],
            }))
      },
    })

    await mirror.replace(identity())
    await mirror.replace(identity('ag'))

    assert.deepEqual(mirror.points.value, [])
    assert.equal(mirror.memberDataset.value, null)
    assert.equal(mirror.canonicalEnd.value, null)
    assert.equal(mirror.error.value, '主力照妖镜 V2 暂不可用')
  })

  it('clears V2 state when a non-null malformed page cursor response arrives', async () => {
    let calls = 0
    const mirror = useMainForceMirrorV2({
      fetchPage: async () => {
        calls += 1
        return calls === 1
          ? normalizedPage()
          : normalizeMainForceMirrorV2Page(malformedPage((page) => {
              nested(page, 'request').symbol = 'ag'
              const pageMeta = nested(page, 'page')
              pageMeta.has_more_before = 'yes'
              pageMeta.next_before = 1
            }))
      },
    })

    await mirror.replace(identity())
    await mirror.replace(identity('ag'))

    assert.deepEqual(mirror.points.value, [])
    assert.equal(mirror.memberDataset.value, null)
    assert.equal(mirror.canonicalEnd.value, null)
    assert.equal(mirror.error.value, '主力照妖镜 V2 暂不可用')
  })

  it('prepends an overlapping V2 page by its own cursor and retains ascending bar_end order', async () => {
    const requests: MainForceMirrorV2PageRequest[] = []
    const mirror = useMainForceMirrorV2({
      fetchPage: async (request) => {
        requests.push(request)
        return request.before === null
          ? normalizedPage({
              points: [
                wirePoint('2026-08-20T02:30:00Z'),
                wirePoint('2026-08-20T03:30:00Z'),
              ],
              page: { has_more_before: true, next_before: '2026-08-20T02:30:00Z' },
            })
          : normalizedPage({
              request: { ...request, contract: request.contract ?? null },
              points: [
                wirePoint('2026-08-20T01:30:00Z'),
                wirePoint('2026-08-20T02:30:00Z', { instant_pressure: 99 }),
              ],
              page: { has_more_before: false, next_before: null },
            })
      },
    })

    await mirror.replace(identity())
    await mirror.loadMoreBefore()

    assert.deepEqual(requests.map((request) => request.before), [null, '2026-08-20T02:30:00Z'])
    assert.deepEqual(mirror.points.value.map((point) => [point.bar_end, point.instant_pressure]), [
      ['2026-08-20T01:30:00Z', 36.2],
      ['2026-08-20T02:30:00Z', 99],
      ['2026-08-20T03:30:00Z', 36.2],
    ])
    assert.equal(mirror.canonicalEnd.value, '2026-08-20T03:30:00Z')
  })

  it('rejects a pagination response whose request, indicator, or member dataset drifts', async () => {
    const driftedPages: Array<Partial<MainForceMirrorV2PageWireResponse>> = [
      { request: { ...mirrorPage().request, before: '2026-08-20T02:30:00Z', symbol: 'ag' } },
      { indicator: { ...mirrorPage().indicator, parameters_hash: 'different-parameters' } },
      { member_dataset: { ...mirrorPage().member_dataset, dataset_id: 'different-member-dataset' } },
    ]

    for (const drift of driftedPages) {
      const mirror = useMainForceMirrorV2({
        fetchPage: async (request) => request.before === null
          ? normalizedPage({ page: { has_more_before: true, next_before: '2026-08-20T02:30:00Z' } })
          : normalizedPage({
              request: { ...request, contract: request.contract ?? null },
              ...drift,
            }),
      })

      await mirror.replace(identity())
      await mirror.loadMoreBefore()

      assert.deepEqual(mirror.points.value, [])
      assert.equal(mirror.memberDataset.value, null)
      assert.equal(mirror.canonicalEnd.value, null)
      assert.equal(mirror.error.value, '主力照妖镜 V2 暂不可用')
    }
  })
})
