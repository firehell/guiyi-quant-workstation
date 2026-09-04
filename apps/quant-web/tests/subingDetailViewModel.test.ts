import assert from 'node:assert/strict'
import test from 'node:test'
import { buildSubingDetailViewModel } from '../src/utils/subingDetailViewModel.ts'

const identity = { view: 'subing' as const, symbol: 'jm', seriesKind: 'actual_dominant' as const, frequency: '15m' as const }
const header = { displayContract: 'JM2601', asOf: '2026-09-04T01:00:00Z' }
const event = { id: 7, rule_code: 'subing_ths_alert_15m_v1' as const, symbol: 'jm', contract: 'JM2601', trading_day: '2026-09-04', frequency: '15m' as const, bar_end: '2026-09-04T01:00:00Z', result_codes: ['buy'] as ['buy'], detected_at: '2026-09-04T01:00:01Z', notification_attempted_at: null }

test('renders exactly three sourced SuBing facts and immutable Event history', () => {
  const model = buildSubingDetailViewModel({ identity, header, events: [event], alertUnavailable: false, rule: 'Rule 已启用 · 当前 Scope 已启用', ruleUnavailable: false, runtime: { status: 'ok', enabled_rule_count: 2, rule_status: { htdy_original_15m: { last_completed_bar_at: null, last_success_at: null, last_failure_at: null, last_error_type: null }, subing_ths_alert_15m_v1: { last_completed_bar_at: event.bar_end, last_success_at: event.detected_at, last_failure_at: null, last_error_type: null } } }, runtimeUnavailable: false })
  assert.equal(model.facts.length, 3)
  assert.match(model.facts[0].value, /S↑ 多头预警/)
  assert.match(model.facts[1].value, /JM2601/)
  assert.equal(model.history[0]?.id, 'subing-event:7')
  assert.match(model.semanticBanner.text, /只来自 AlertEvent/)
})

test('does not turn no Event or an unavailable initial snapshot into a neutral signal', () => {
  const model = buildSubingDetailViewModel({ identity, header, events: [], alertUnavailable: true, rule: null, ruleUnavailable: true, runtime: null, runtimeUnavailable: true })
  assert.match(model.facts[0].value, /预警数据不可用/)
  assert.match(model.facts[1].value, /不可用/)
  assert.equal(model.history.length, 0)
})
