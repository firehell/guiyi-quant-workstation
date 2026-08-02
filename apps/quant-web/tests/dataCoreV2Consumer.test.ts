import assert from 'node:assert/strict'
import { describe, it } from 'node:test'

import {
  buildFormalBacktestRequest,
  buildFormalSignalScanRequest,
  presentCanonicalInputIdentity,
} from '../src/utils/dataCoreV2Consumer.ts'

describe('data core v2 trusted consumers', () => {
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

  it('presents the persisted canonical input identity rather than Profile or binding fields', () => {
    const presentation = presentCanonicalInputIdentity({
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
          provider: 'rqdata',
          dataset_kind: 'actual_dominant',
          symbol: 'jm',
          contract_or_series: 'JM2609',
          frequency: '1m',
          adjustment: 'none',
          schema_version: 'canonical-bar-v1',
        },
      ],
      manifest_digests: ['a'.repeat(64)],
      source_data_versions: ['rqdata-20260731'],
      derived_frequency: '15m',
      strategy_input_version: 'signal:su_bing_ema21:v0',
      digest: 'b'.repeat(64),
    })

    assert.equal(presentation.request, 'actual_dominant · jm · JM2609 · 15m')
    assert.equal(presentation.sourceDatasets, 'rqdata · actual_dominant · jm · JM2609 · 1m')
    assert.equal(presentation.manifestDigests, 'a'.repeat(64))
    assert.equal(presentation.requestedWindow, '2026-07-01T00:00:00+00:00 → 2026-07-31T00:00:00+00:00')
    assert.equal(presentation.digest, 'b'.repeat(64))
  })
})
