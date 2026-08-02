import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { describe, it } from 'node:test'
import { fileURLToPath } from 'node:url'

import {
  buildReviewFoundationContext,
  foundationFieldLabel,
  reviewSourceIdentity,
} from '../src/utils/reviewFoundation.ts'
import type { ReviewFoundationInput } from '../src/types/reviewFoundation.ts'

const fixtureDir = join(dirname(fileURLToPath(import.meta.url)), 'fixtures/reviewFoundation')

function loadFixture(name: string): ReviewFoundationInput & { fixture_id?: string; report_id?: null } {
  return JSON.parse(readFileSync(join(fixtureDir, name), 'utf8')) as ReviewFoundationInput & {
    fixture_id?: string
    report_id?: null
  }
}

describe('reviewFoundation', () => {
  it('builds validated fixture without inventing ids', () => {
    const fixture = loadFixture('validated.json')
    assert.equal(fixture.report_id, null)
    const ctx = buildReviewFoundationContext(fixture)
    assert.equal(ctx.strategy_code.status, 'available')
    assert.equal(ctx.strategy_code.value, 'huotian_dayou_strict')
    assert.equal(ctx.candidate_status.value, 'validated_research_candidate')
    assert.equal(ctx.oos_window_id.value, 'oos_fixed')
    assert.equal(ctx.walk_forward_fold_id.status, 'unavailable')
    assert.equal(ctx.lineage_status.value, 'ready')
    assert.equal(ctx.signal_bar.status, 'available')
    assert.equal(ctx.next_bar_fill.status, 'available')
  })

  it('builds rejected fixture', () => {
    const ctx = buildReviewFoundationContext(loadFixture('rejected.json'))
    assert.equal(ctx.candidate_status.value, 'rejected_research_candidate')
    assert.equal(ctx.walk_forward_fold_id.value, 'walk_forward_a_test')
    assert.equal(ctx.hard_reject_reason.status, 'unavailable')
  })

  it('builds hard_reject fixture', () => {
    const ctx = buildReviewFoundationContext(loadFixture('hard_reject.json'))
    assert.equal(ctx.candidate_status.value, 'oos_hard_rejected')
    assert.equal(ctx.hard_reject_reason.value, 'max_drawdown_pct_gt_0.15')
    assert.match(foundationFieldLabel(ctx.hard_reject_reason), /max_drawdown/)
  })

  it('builds skipped frozen hard reject with lineage unavailable', () => {
    const ctx = buildReviewFoundationContext(loadFixture('skipped_frozen_hard_reject.json'))
    assert.equal(ctx.review_skip_status.value, 'SKIPPED_BY_FROZEN_HARD_REJECT')
    assert.equal(ctx.lineage_status.status, 'unavailable')
    assert.equal(ctx.signal_bar.status, 'unavailable')
    assert.equal(ctx.canonical_input_identity.status, 'unavailable')
  })

  it('marks empty input fields unavailable without inventing values', () => {
    const ctx = buildReviewFoundationContext({})
    assert.equal(ctx.strategy_code.status, 'unavailable')
    assert.equal(ctx.indicator_policy_status.status, 'unavailable')
    assert.equal(ctx.oos_window_id.status, 'unavailable')
    assert.equal(ctx.candidate_status.status, 'unavailable')
    assert.equal(ctx.review_skip_status.status, 'unavailable')
    assert.equal(ctx.lineage_status.status, 'unavailable')
  })

  it('shows legacy policy as warning, not invented snapshot', () => {
    const ctx = buildReviewFoundationContext({
      report: {
        indicator_policy_status: 'legacy_policy_unavailable',
        indicator_policy_snapshot: null,
        indicator_policy_reason: 'no snapshot on legacy report',
      },
    })
    assert.equal(ctx.indicator_policy_status.status, 'warning')
    assert.equal(ctx.indicator_policy_summary.status, 'unavailable')
  })

  it('uses hash-valid validation context for OOS WF and rejection fields', () => {
    const ctx = buildReviewFoundationContext({
      report: {
        oos_window_id: 'must-not-win',
        candidate_status: 'must-not-win',
      },
      validation_context: {
        schema_version: 'backtest_validation_context_x506b_v1',
        report_id: 15,
        candidate_status: 'oos_hard_rejected',
        review_skip_status: 'SKIPPED_BY_FROZEN_HARD_REJECT',
        candidate: { gate: 'HTDY_TRUSTED_BACKTEST_CANDIDATE' },
        oos: {
          window_id: 'oos_fixed',
          gate: 'OOS_HARD_REJECT_TRIGGERED',
          metrics: { trade_count: 179, profit_factor: 0.16 },
          hard_reject: { numeric_reasons: ['profit_factor_lt_0.5'] },
        },
        rolling_oos: {
          mode: 'rolling_oos_stability',
          proposal_label: 'DIAGNOSTIC_CONFIRMS_REJECTION',
          folds: [
            { fold_id: 'walk_forward_a_test', trade_count: 84 },
            { fold_id: 'walk_forward_b_test', trade_count: 101 },
            { fold_id: 'walk_forward_c_test', trade_count: 166 },
          ],
        },
        binding_identity: { profile_id: 'intraday_research_v1' },
        evidence_hashes: { context_hash: 'a'.repeat(64) },
        context_hash: 'b'.repeat(64),
      },
    })

    assert.equal(ctx.oos_window_id.value, 'oos_fixed')
    assert.equal(ctx.candidate_status.value, 'oos_hard_rejected')
    assert.equal(ctx.review_skip_status.value, 'SKIPPED_BY_FROZEN_HARD_REJECT')
    assert.match(String(ctx.walk_forward_fold_id.value), /walk_forward_c_test/)
    assert.equal(ctx.oos_gate.value, 'OOS_HARD_REJECT_TRIGGERED')
    assert.equal(ctx.rolling_proposal.value, 'DIAGNOSTIC_CONFIRMS_REJECTION')
    assert.match(String(ctx.hard_reject_reason.value), /profit_factor/)
  })

  it('formats an exact review source identity without inventing missing links', () => {
    assert.equal(
      reviewSourceIdentity({
        source_type: 'backtest_trade',
        source_id: 88,
        report_id: 14,
        trade_id: 88,
      }),
      'backtest_trade · report #14 · trade #88',
    )
    assert.equal(
      reviewSourceIdentity({
        source_type: 'signal_event',
        source_id: 7,
      }),
      'signal_event #7',
    )
    assert.equal(
      reviewSourceIdentity({
        source_type: 'strategy_signal',
      }),
      'strategy_signal · source unavailable',
    )
  })
})
