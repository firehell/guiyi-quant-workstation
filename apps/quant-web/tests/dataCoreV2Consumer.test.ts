import assert from 'node:assert/strict'
import { describe, it } from 'node:test'

import {
  buildFormalBacktestRequest,
  buildFormalSignalScanRequest,
  normalizeFormalSignalDateRange,
  parseCanonicalInputIdentity,
  presentCanonicalInputIdentity,
  validateFormalSignalScanInput,
  validateFormalSignalRiskPercentages,
} from '../src/utils/dataCoreV2Consumer.ts'

describe('data core v2 trusted consumers', () => {
  const canonicalIdentity = () => ({
    schema_version: 'canonical_consumer_input_v1',
    request: {
      dataset_kind: 'actual_dominant',
      symbol: 'jm',
      contract_or_series: 'JM2609',
      frequency: '15m',
      start: '2026-07-01T00:00:00+00:00',
      end: '2026-07-31T00:00:00+00:00',
      strict: true,
    },
    source_datasets: [
      {
        provider: 'rqdata', dataset_kind: 'actual_dominant', symbol: 'jm', contract_or_series: 'JM2609',
        frequency: '1m', adjustment: 'none', schema_version: 'canonical-bar-v1',
      },
    ],
    manifest_digests: ['a'.repeat(64)],
    source_data_versions: ['rqdata-20260731'],
    derived_frequency: '15m',
    strategy_input_version: 'signal:su_bing_ema21:v0',
    digest: 'b'.repeat(64),
  })

  it('serializes a formal backtest with DatasetKey identity and no legacy Profile fields', () => {
    const request = buildFormalBacktestRequest({
      engine_type: 'vnpy',
      task_type: 'single',
      dataset_kind: 'actual_dominant',
      instrument_symbol: ' jm ',
      contract_or_series: ' jm2609 ',
      exchange: 'DCE',
      interval: '15m',
      start: '2026-07-01T00:00:00.000Z',
      end: '2026-07-31T00:00:00.000Z',
      strategy_class_path: 'guiyi_quant.strategies.su_bing_ema21.vnpy_strategy.SuBingEma21VnpyStrategy',
      strategy_code: 'su_bing_ema21',
      strategy_version: 'v0',
      strategy_parameters: { ema_period: 21 },
      rate: 0.0001,
      slippage: 1,
      size: 10,
      pricetick: 1,
      capital: 100000,
      profile_id: 'legacy-profile',
      market_data_file_id: 7,
      binding_snapshot: { legacy: true },
    } as never)

    assert.deepEqual(request, {
      engine_type: 'vnpy',
      task_type: 'single',
      dataset_kind: 'actual_dominant',
      instrument_symbol: 'jm',
      contract_or_series: 'JM2609',
      exchange: 'DCE',
      interval: '15m',
      start: '2026-07-01T00:00:00.000Z',
      end: '2026-07-31T00:00:00.000Z',
      strategy_class_path: 'guiyi_quant.strategies.su_bing_ema21.vnpy_strategy.SuBingEma21VnpyStrategy',
      strategy_code: 'su_bing_ema21',
      strategy_version: 'v0',
      strategy_parameters: { ema_period: 21 },
      rate: 0.0001,
      slippage: 1,
      size: 10,
      pricetick: 1,
      capital: 100000,
    })
    assert.equal('profile_id' in request, false)
    assert.equal('market_data_file_id' in request, false)
    assert.equal('binding_snapshot' in request, false)
  })

  it('serializes non-scan formal signal modes for the zero-write preview contract', () => {
    const request = buildFormalSignalScanRequest({
      dataset_kind: 'actual_dominant',
      instrument_symbol: 'JM',
      contract_or_series: 'jm2609',
      periods: ['15m'],
      start: '2026-07-01T00:00:00.000Z',
      end: '2026-07-31T00:00:00.000Z',
      mode: 'replay',
      watchlist_code: 'black',
      account_equity: 100000,
      risk_per_trade_pct: 0.01,
      max_margin_usage_pct: 0.35,
      min_score_bucket: 51,
    })

    assert.deepEqual(request, {
      dataset_kind: 'actual_dominant',
      instrument_symbol: 'jm',
      contract_or_series: 'JM2609',
      periods: ['15m'],
      start: '2026-07-01T00:00:00.000Z',
      end: '2026-07-31T00:00:00.000Z',
      mode: 'replay',
      watchlist_code: 'black',
      account_equity: 100000,
      risk_per_trade_pct: 0.01,
      max_margin_usage_pct: 0.35,
      min_score_bucket: 51,
    })
  })

  it('accepts backend-aligned signal risk percentage boundaries and blocks values above them', () => {
    assert.equal(validateFormalSignalRiskPercentages(1, 35), null)
    assert.match(String(validateFormalSignalRiskPercentages(1.1, 35)), /1%/)
    assert.match(String(validateFormalSignalRiskPercentages(1, 35.1)), /35%/)
  })

  it('blocks formal Signal requests with a missing concrete contract, unsupported week, empty periods, or invalid window', () => {
    const valid = {
      contractOrSeries: 'JM2609', periods: ['15m'], startMs: 10, endMs: 20, riskPerTradePercent: 1, maxMarginUsagePercent: 35,
    }
    assert.equal(validateFormalSignalScanInput(valid), null)
    assert.match(String(validateFormalSignalScanInput({ ...valid, contractOrSeries: 'JM.MAIN' })), /实际主力合约/)
    assert.match(String(validateFormalSignalScanInput({ ...valid, periods: ['1w'] })), /1w/)
    assert.match(String(validateFormalSignalScanInput({ ...valid, periods: [] })), /周期/)
    assert.match(String(validateFormalSignalScanInput({ ...valid, startMs: 20, endMs: 20 })), /时间窗口/)
  })

  it('rejects unsupported, malformed, bad-digest, and legacy identities before Signal can label them canonical', () => {
    const unsupported = canonicalIdentity()
    unsupported.schema_version = 'legacy_input_v1'
    assert.equal(parseCanonicalInputIdentity(unsupported, { expectedDatasetKind: 'actual_dominant' }).status, 'unavailable')

    const malformedDatasets = canonicalIdentity()
    malformedDatasets.source_datasets = [{}] as never
    assert.equal(parseCanonicalInputIdentity(malformedDatasets, { expectedDatasetKind: 'actual_dominant' }).status, 'unavailable')

    const badDigest = canonicalIdentity()
    badDigest.manifest_digests = ['not-a-sha']
    assert.equal(parseCanonicalInputIdentity(badDigest, { expectedDatasetKind: 'actual_dominant' }).status, 'unavailable')

    const continuous = canonicalIdentity()
    continuous.request.dataset_kind = 'continuous'
    assert.equal(parseCanonicalInputIdentity(continuous, { expectedDatasetKind: 'actual_dominant' }).status, 'unavailable')

    assert.equal(parseCanonicalInputIdentity({ profile_id: 'legacy' }, { expectedDatasetKind: 'actual_dominant' }).status, 'unavailable')
  })

  it('rejects backend-invalid canonical identity snapshots in a table-driven contract suite', () => {
    const cases: Array<{ name: string; mutate: (identity: any) => void }> = [
      { name: 'extra top-level field', mutate: (identity) => { identity.extra = true } },
      { name: 'missing request field', mutate: (identity) => { delete identity.request.strict } },
      { name: 'uppercase request symbol is not canonical', mutate: (identity) => { identity.request.symbol = 'JM' } },
      { name: 'lowercase actual contract is not canonical', mutate: (identity) => { identity.request.contract_or_series = 'jm2609' } },
      { name: 'unsupported request frequency', mutate: (identity) => { identity.request.frequency = '2m' } },
      { name: 'actual-dominant weekly request is unsupported', mutate: (identity) => { identity.request.frequency = '1w' } },
      { name: 'timezone-less request start', mutate: (identity) => { identity.request.start = '2026-07-01T00:00:00' } },
      { name: 'non-increasing request window', mutate: (identity) => { identity.request.end = identity.request.start } },
      { name: 'non-rqdata source provider', mutate: (identity) => { identity.source_datasets[0].provider = 'other' } },
      { name: 'non-canonical source adjustment', mutate: (identity) => { identity.source_datasets[0].adjustment = ' None ' } },
      { name: 'unsupported source frequency', mutate: (identity) => { identity.source_datasets[0].frequency = '15m' } },
      { name: 'source dataset request mismatch', mutate: (identity) => { identity.source_datasets[0].symbol = 'i' } },
      { name: 'derived request source must be 1m', mutate: (identity) => { identity.source_datasets[0].frequency = '1d' } },
      { name: 'derived frequency must match request', mutate: (identity) => { identity.derived_frequency = '5m' } },
      { name: 'unordered duplicate manifests', mutate: (identity) => { identity.manifest_digests = ['b'.repeat(64), 'a'.repeat(64), 'a'.repeat(64)] } },
      { name: 'non-canonical source version', mutate: (identity) => { identity.source_data_versions = [' version '] } },
    ]

    for (const testCase of cases) {
      const identity = canonicalIdentity() as any
      testCase.mutate(identity)
      assert.equal(
        parseCanonicalInputIdentity(identity, { expectedDatasetKind: 'actual_dominant' }).status,
        'unavailable',
        testCase.name,
      )
    }
  })

  it('accepts backend-valid nullable actual-dominant and continuous identities', () => {
    const resolvedActual = canonicalIdentity() as any
    resolvedActual.request.contract_or_series = null
    assert.equal(parseCanonicalInputIdentity(resolvedActual, { expectedDatasetKind: 'actual_dominant' }).status, 'unverified')

    const continuous = canonicalIdentity() as any
    continuous.request.dataset_kind = 'continuous'
    continuous.request.contract_or_series = 'JM.MAIN'
    continuous.source_datasets[0].dataset_kind = 'continuous'
    continuous.source_datasets[0].contract_or_series = 'JM.MAIN'
    continuous.request.frequency = '1d'
    continuous.source_datasets[0].frequency = '1d'
    continuous.derived_frequency = null
    assert.equal(parseCanonicalInputIdentity(continuous, { expectedDatasetKind: 'continuous' }).status, 'unverified')

    const microsecondWindow = canonicalIdentity() as any
    microsecondWindow.request.start = '2026-07-01T00:00:00.000001+00:00'
    microsecondWindow.request.end = '2026-07-01T00:00:00.000002+00:00'
    assert.equal(parseCanonicalInputIdentity(microsecondWindow, { expectedDatasetKind: 'actual_dominant' }).status, 'unverified')
  })

  it('blocks formal Signal contracts that backend will reject and preserves a clearable empty date range', () => {
    const valid = {
      contractOrSeries: 'JM2609', periods: ['15m'], startMs: 10, endMs: 20, riskPerTradePercent: 1, maxMarginUsagePercent: 35,
    }
    for (const contract of ['jm2609', 'ABC2609', 'JM-2609', 'I2609', 'JM.MAIN']) {
      assert.match(String(validateFormalSignalScanInput({ ...valid, contractOrSeries: contract })), /JM\\d\{3,4\}/)
    }
    assert.deepEqual(normalizeFormalSignalDateRange(null), { startMs: null, endMs: null })
    assert.match(String(validateFormalSignalScanInput({ ...valid, startMs: null, endMs: null })), /时间窗口/)
  })

  it('presents the persisted canonical input identity rather than Profile or binding fields', () => {
    const presentation = presentCanonicalInputIdentity(canonicalIdentity())

    assert.equal(presentation.status, 'unverified')
    assert.equal(presentation.request, 'actual_dominant · jm · JM2609 · 15m')
    assert.equal(presentation.sourceDatasets, 'rqdata · actual_dominant · jm · JM2609 · 1m')
    assert.equal(presentation.manifestDigests, 'a'.repeat(64))
    assert.equal(presentation.requestedWindow, '2026-07-01T00:00:00+00:00 → 2026-07-31T00:00:00+00:00')
    assert.equal(presentation.digest, 'b'.repeat(64))
  })
})
