import assert from 'node:assert/strict'
import test from 'node:test'

import { normalizeRuntimeAlertProjection } from '../src/utils/runtimeHealthTypes.ts'

const ruleStatus = {
  last_completed_bar_at: '2026-09-04T01:00:00+08:00',
  last_success_at: '2026-09-04T01:00:01+08:00',
  last_failure_at: null,
  last_error_type: null,
}

test('accepts only the exact schema-v6 two-rule runtime projection', () => {
  const projection = normalizeRuntimeAlertProjection({
    status: 'ok', enabled_rule_count: 2,
    rule_status: { htdy_original_15m: ruleStatus, subing_ths_alert_15m_v1: ruleStatus },
  })
  assert.equal(projection.enabled_rule_count, 2)
  assert.equal(projection.rule_status.subing_ths_alert_15m_v1.last_error_type, null)
})

test('rejects missing keys, malformed timestamps, and unknown per-rule errors', () => {
  assert.throws(() => normalizeRuntimeAlertProjection({ status: 'ok', enabled_rule_count: 2, rule_status: { htdy_original_15m: ruleStatus } }))
  assert.throws(() => normalizeRuntimeAlertProjection({ status: 'ok', enabled_rule_count: 2, rule_status: { htdy_original_15m: ruleStatus, subing_ths_alert_15m_v1: { ...ruleStatus, last_success_at: '2026-09-04T01:00:01' } } }))
  assert.throws(() => normalizeRuntimeAlertProjection({ status: 'ok', enabled_rule_count: 2, rule_status: { htdy_original_15m: ruleStatus, subing_ths_alert_15m_v1: { ...ruleStatus, last_error_type: 'unexpected' } } }))
})
