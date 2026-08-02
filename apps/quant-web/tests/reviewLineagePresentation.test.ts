import assert from 'node:assert/strict'
import { describe, it } from 'node:test'

import { presentReviewLineage } from '../src/utils/reviewLineagePresentation.ts'

describe('review lineage presentation', () => {
  it('renders canonical lineage from exact input identity', () => {
    const result = presentReviewLineage({
      schema_version: 'review_canonical_lineage_v1',
      source_type: 'backtest_trade',
      source_id: 7,
      input_digest: 'b'.repeat(64),
      dataset_keys: [
        {
          provider: 'rqdata', dataset_kind: 'actual_dominant', symbol: 'jm', contract_or_series: 'JM2609',
          frequency: '1m', adjustment: 'none', schema_version: 'canonical-bar-v1',
        },
      ],
      manifest_digests: ['a'.repeat(64)],
      window: { start: '2026-07-01T00:00:00+00:00', end: '2026-07-31T00:00:00+00:00' },
      source_window: { start: '2026-07-11T01:00:00+00:00', end: '2026-07-11T02:00:00+00:00' },
      input_identity: {
        schema_version: 'canonical_consumer_input_v1',
        request: {
          dataset_kind: 'actual_dominant', symbol: 'jm', contract_or_series: 'JM2609', frequency: '15m',
          start: '2026-07-01T00:00:00+00:00', end: '2026-07-31T00:00:00+00:00', strict: true,
        },
        source_datasets: [
          {
            provider: 'rqdata', dataset_kind: 'actual_dominant', symbol: 'jm', contract_or_series: 'JM2609',
            frequency: '1m', adjustment: 'none', schema_version: 'canonical-bar-v1',
          },
        ], manifest_digests: ['a'.repeat(64)], source_data_versions: [],
        derived_frequency: '15m', strategy_input_version: 'backtest:su_bing_ema21:v0', digest: 'b'.repeat(64),
      },
    })

    assert.equal(result.kind, 'canonical')
    assert.equal(result.inputDigest, 'b'.repeat(64))
    assert.equal(result.canonical.request, 'actual_dominant · jm · JM2609 · 15m')
    assert.equal(result.canonical.manifestDigests, 'a'.repeat(64))
    assert.equal(result.requestedWindow, '2026-07-01T00:00:00+00:00 → 2026-07-31T00:00:00+00:00')
  })

  it('keeps legacy live observation lineage distinct and never accesses canonical-only fields', () => {
    const result = presentReviewLineage({
      schema_version: 'review_source_lineage_v1',
      source_type: 'signal_event',
      source_id: 9,
      source_snapshot_schema_version: 'signal_review_lineage_v2',
      source_mode: 'live_realtime_repainting',
      bar: {
        bar_start: '2026-07-11T01:00:00+00:00',
        bar_end: '2026-07-11T01:15:00+00:00',
        confirmation_mode: 'live_realtime_repainting',
      },
    })

    assert.equal(result.kind, 'observation')
    assert.equal(result.sourceMode, 'live_realtime_repainting')
    assert.equal(result.sourceWindow, '2026-07-11T01:00:00+00:00 → 2026-07-11T01:15:00+00:00')
    assert.match(result.label, /observation/i)
  })
})
