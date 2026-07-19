import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { describe, it } from 'node:test'
import { fileURLToPath } from 'node:url'

import {
  buildReviewFoundationContext,
  foundationFieldLabel,
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
    assert.equal(ctx.binding_snapshot_present.status, 'unavailable')
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
})
