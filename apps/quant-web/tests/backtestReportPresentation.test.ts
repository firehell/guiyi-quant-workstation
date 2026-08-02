import assert from 'node:assert/strict'
import { describe, it } from 'node:test'

import { buildBacktestReportPresentation } from '../src/utils/backtestReportPresentation.ts'

describe('backtest report presentation', () => {
  it('separates a passed trust audit from strategy validity', () => {
    const result = buildBacktestReportPresentation(
      {
        id: 14,
        report_no: 'BT-14',
        input_identity: {
          schema_version: 'canonical_consumer_input_v1',
          request: {
            dataset_kind: 'actual_dominant', symbol: 'jm', contract_or_series: 'JM2609', frequency: '15m',
            start: '2026-07-01T00:00:00+00:00', end: '2026-07-31T00:00:00+00:00', strict: true,
          },
          source_datasets: [], manifest_digests: ['a'.repeat(64)], source_data_versions: [],
          derived_frequency: null, strategy_input_version: 'backtest:su_bing_ema21:v0', digest: 'b'.repeat(64),
        },
        candidate_status: 'oos_hard_rejected',
        hard_reject_reason: 'max_drawdown_pct_gt_0.15',
        summary: { report_metadata: { cost_model_version: 'cost_model_v1' } },
      },
      {
        available: true,
        context: {
          candidate: { candidate_trust_audit: 'passed' },
          candidate_status: 'oos_hard_rejected',
          hard_reject_reason: 'max_drawdown_pct_gt_0.15',
          oos: { window_id: 'oos_fixed', gate: 'OOS_HARD_REJECT_TRIGGERED' },
        },
      },
    )

    assert.equal(result.identity, 'BT-14 · report #14')
    assert.equal(result.trustAudit, 'passed')
    assert.equal(result.canonicalInput.request, 'actual_dominant · jm · JM2609 · 15m')
    assert.equal(result.canonicalInput.digest, 'b'.repeat(64))
    assert.equal(result.candidateStatus, 'oos_hard_rejected')
    assert.equal(result.oosGate, 'OOS_HARD_REJECT_TRIGGERED')
    assert.match(result.boundary, /不等于策略有效/)
  })

  it('keeps missing validation evidence unavailable', () => {
    const result = buildBacktestReportPresentation(
      {
        id: 9,
        report_no: 'BT-9',
        summary: {},
      },
      {
        available: false,
        error_type: 'BACKTEST_VALIDATION_EVIDENCE_INVALID',
      },
    )

    assert.equal(result.trustAudit, 'unavailable')
    assert.equal(result.validationEvidence, 'BACKTEST_VALIDATION_EVIDENCE_INVALID')
    assert.equal(result.canonicalInput.digest, 'unavailable')
  })
})
