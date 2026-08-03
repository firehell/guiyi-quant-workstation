import assert from 'node:assert/strict'
import { describe, it } from 'node:test'

import {
  getMarketBarsForBacktestReport,
  toCanonicalBarsRequest,
  toCanonicalIndicatorsRequest,
  toCanonicalReportBarsQuery,
} from '../src/utils/dataCoreV2Market.ts'

const verifiedIdentity = {
  schema_version: 'canonical_consumer_input_v1' as const,
  request: {
    dataset_kind: 'actual_dominant' as const,
    symbol: 'jm',
    contract_or_series: null,
    frequency: '15m',
    start: '2026-07-01T00:00:00+00:00',
    end: '2026-07-31T00:00:00+00:00',
    strict: true,
  },
  source_datasets: [{
    provider: 'rqdata',
    dataset_kind: 'actual_dominant' as const,
    symbol: 'jm',
    contract_or_series: 'JM2609',
    frequency: '15m',
    adjustment: 'none',
    schema_version: 'canonical-bar-v1',
  }],
  manifest_digests: ['a'.repeat(64)],
  source_data_versions: ['rqdata-20260731'],
  derived_frequency: null,
  strategy_input_version: 'backtest:su_bing_ema21:v0',
  digest: 'a5389cfe5965b623f00ff3c68fd896e3fb6c36aeba8027a89e4a7212672b8d3a',
}

const serverAttestation = {
  schema_version: 'canonical_consumer_input_attestation_v1' as const,
  status: 'server_verified' as const,
  digest: verifiedIdentity.digest,
}

function verifiedReport(overrides: Record<string, unknown> = {}) {
  return {
    input_identity: verifiedIdentity,
    input_identity_attestation: serverAttestation,
    ...overrides,
  } as never
}

describe('dataCoreV2Market', () => {
  it('builds an explicit continuous canonical bars request without legacy selectors', () => {
    assert.deepEqual(
      toCanonicalBarsRequest({
        dataset_kind: 'continuous',
        symbol: 'jm',
        contract: 'jm.MAIN',
        period: '15m',
        start: '2026-07-01T01:00:00Z',
        end: '2026-07-02T01:00:00Z',
        profile_id: 'legacy-profile',
        expected_lineage_token: 'legacy-token',
        tail: true,
        limit: 10000,
      }),
      {
        dataset_kind: 'continuous',
        symbol: 'jm',
        contract_or_series: 'jm.MAIN',
        frequency: '15m',
        start: '2026-07-01T01:00:00Z',
        end: '2026-07-02T01:00:00Z',
      },
    )
  })

  it('builds an explicit actual-dominant canonical indicator request', () => {
    assert.deepEqual(
      toCanonicalIndicatorsRequest({
        dataset_kind: 'actual_dominant',
        symbol: 'jm',
        contract: 'JM2609',
        period: '1m',
        indicator_codes: 'ema10,ema21',
        display_start: '2026-07-01T01:00:00Z',
        display_end: '2026-07-01T02:00:00Z',
        display_bar_count: 60,
      }),
      {
        dataset_kind: 'actual_dominant',
        symbol: 'jm',
        contract_or_series: 'JM2609',
        frequency: '1m',
        start: '2026-07-01T01:00:00Z',
        end: '2026-07-01T02:00:00Z',
        indicator_codes: 'ema10,ema21',
        display_bar_count: 60,
      },
    )
  })

  it('fails closed when canonical bars have no exact window', () => {
    assert.throws(
      () =>
        toCanonicalBarsRequest({
          dataset_kind: 'actual_dominant',
          symbol: 'jm',
          contract: 'JM2609',
          period: '1m',
        }),
      /exact_start_end_required/,
    )
  })

  it('fails closed on date-only canonical windows before calling FastAPI', () => {
    assert.throws(
      () =>
        toCanonicalBarsRequest({
          dataset_kind: 'continuous',
          symbol: 'jm',
          contract: 'JM.MAIN',
          period: '1d',
          start: '2026-07-01',
          end: '2026-07-02',
        }),
      /start_rfc3339_timezone_required/,
    )
  })

  it('accepts a canonical request for any catalog product', () => {
    assert.deepEqual(
      toCanonicalBarsRequest({
          dataset_kind: 'actual_dominant',
          symbol: 'i',
          contract: 'I2609',
          period: '1m',
          start: '2026-07-01T01:00:00Z',
          end: '2026-07-01T02:00:00Z',
        }),
      {
        dataset_kind: 'actual_dominant',
        symbol: 'i',
        contract_or_series: 'I2609',
        frequency: '1m',
        start: '2026-07-01T01:00:00Z',
        end: '2026-07-01T02:00:00Z',
      },
    )
  })

  it('replays a canonical backtest report from its frozen input identity without legacy fallback', () => {
    const query = toCanonicalReportBarsQuery(verifiedReport())

    assert.deepEqual(query.attempted, [{
      dataset_kind: 'actual_dominant',
      symbol: 'jm',
      contract: null,
      period: '15m',
      start: '2026-07-01T00:00:00+00:00',
      end: '2026-07-31T00:00:00+00:00',
    }])
    assert.equal(query.dataset_kind, 'actual_dominant')
    assert.equal(query.contract, null)
    assert.equal('profile_id' in query.attempted[0], false)
    assert.equal('market_data_file_id' in query.attempted[0], false)
  })

  it('fails closed when a historical report has only legacy Profile lineage', () => {
    assert.throws(
      () => toCanonicalReportBarsQuery({
        input_identity: null,
        profile_id: 'intraday_research_v1',
        market_data_file_id: 7,
      } as never),
      /canonical_report_input_identity_required/,
    )
  })

  it('requests canonical report bars exactly once with the attested request', async () => {
    const calls: Array<{ path: string; params: unknown }> = []
    const result = await getMarketBarsForBacktestReport(
      verifiedReport(),
      async (path, params) => {
        calls.push({ path, params })
        return { bars: [{ close: 1001 }] } as never
      },
    )

    assert.deepEqual(calls, [{
      path: '/market/bars/canonical',
      params: {
        dataset_kind: 'actual_dominant',
        symbol: 'jm',
        contract_or_series: null,
        frequency: '15m',
        start: '2026-07-01T00:00:00+00:00',
        end: '2026-07-31T00:00:00+00:00',
      },
    }])
    assert.equal(result.response.bars.length, 1)
  })

  it('does not retry an empty canonical report bars response', async () => {
    let calls = 0
    const result = await getMarketBarsForBacktestReport(
      verifiedReport(),
      async () => {
        calls += 1
        return { bars: [] } as never
      },
    )
    assert.equal(calls, 1)
    assert.deepEqual(result.response.bars, [])
  })

  it('does not retry a canonical report bars error', async () => {
    let calls = 0
    await assert.rejects(
      getMarketBarsForBacktestReport(verifiedReport(), async () => {
        calls += 1
        throw new Error('canonical read failed')
      }),
      /canonical read failed/,
    )
    assert.equal(calls, 1)
  })

  it('makes zero requests for malformed, legacy, or digest-mismatched report identities', async () => {
    let calls = 0
    const requester = async () => {
      calls += 1
      return { bars: [] } as never
    }
    const cases = [
      verifiedReport({ input_identity: { ...verifiedIdentity, request: null } }),
      { input_identity: null, input_identity_attestation: null },
      verifiedReport({
        input_identity_attestation: { ...serverAttestation, digest: 'f'.repeat(64) },
      }),
    ]
    for (const report of cases) {
      await assert.rejects(
        getMarketBarsForBacktestReport(report as never, requester),
        /canonical_report_input_identity_(?:required|attestation_required)/,
      )
    }
    assert.equal(calls, 0)
  })
})
