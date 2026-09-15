import assert from 'node:assert/strict'
import test from 'node:test'
import { buildSubingDetailViewModel } from '../src/utils/subingDetailViewModel.ts'

const identity = { view: 'subing' as const, symbol: 'jm', seriesKind: 'actual_dominant' as const, frequency: '15m' as const }
const header = { displayContract: 'JM2601', asOf: '2026-09-04T01:00:00Z' }
const event = { id: 7, rule_code: 'subing_ths_alert_15m_v1' as const, symbol: 'jm', contract: 'JM2601', trading_day: '2026-09-04', frequency: '15m' as const, bar_end: '2026-09-04T01:00:00Z', result_codes: ['buy'] as ['buy'], detected_at: '2026-09-04T01:00:01Z', notification_attempted_at: null }

test('renders four separate Scope, Runtime, evaluation, and exact Event facts', () => {
  const model = buildSubingDetailViewModel({ identity, header, events: [event], alertUnavailable: false, rule: { ruleCode: 'subing_ths_alert_15m_v1', displayName: '苏冰预警', symbol: 'jm', frequency: '15m', enabled: true, enabledFrequencies: ['15m'] }, ruleUnavailable: false, runtime: { status: 'ok', enabled_rule_count: 2, rule_status: { htdy_original_15m: { last_evaluated_bar_at: null, last_event_at: null, last_failure_at: null, error_type: null }, subing_ths_alert_15m_v1: { last_evaluated_bar_at: event.bar_end, last_event_at: event.detected_at, last_failure_at: null, error_type: null } } }, runtimeUnavailable: false })
  assert.equal(model.facts.length, 4)
  assert.equal(model.facts[0].label, '当前品种 Scope')
  assert.match(model.facts[0].value, /JM 15m 已启用/)
  assert.equal(model.facts[1].label, 'Rule / Runtime')
  assert.match(model.facts[1].value, /苏冰预警.*全局正常/)
  assert.equal(model.facts[2].label, '全局最近评估')
  assert.match(model.facts[2].value, /不代表 JM 已评估/)
  assert.equal(model.facts[3].label, '当前品种已保存 Event')
  assert.match(model.facts[3].value, /S↑ 多头预警/)
  assert.doesNotMatch(model.facts.map((fact) => fact.value).join(' '), /状态不可判定/)
  assert.equal(model.history[0]?.id, 'subing-event:7')
  assert.match(model.semanticBanner.text, /只来自 AlertEvent/)
  assert.match(model.disclosureSections[1]?.rows[0]?.value ?? '', /actual_dominant \/ 15m \/ completed_only/)
})

test('does not turn no Event or an unavailable initial snapshot into a neutral signal', () => {
  const model = buildSubingDetailViewModel({ identity, header, events: [], alertUnavailable: true, rule: null, ruleUnavailable: true, runtime: null, runtimeUnavailable: true })
  assert.match(model.facts[0].value, /Scope 不可用/)
  assert.match(model.facts[3].value, /Event 数据不可用/)
  assert.equal(model.history.length, 0)
})

test('does not treat no exact Event as neutral and ignores another product Event', () => {
  const other = { ...event, id: 8, symbol: 'rb' }
  const model = buildSubingDetailViewModel({ identity, header, events: [other], alertUnavailable: false, rule: { ruleCode: 'subing_ths_alert_15m_v1', displayName: '苏冰预警', symbol: 'jm', frequency: '15m', enabled: false, enabledFrequencies: [] }, ruleUnavailable: false, runtime: { status: 'degraded', enabled_rule_count: 1, rule_status: { htdy_original_15m: { last_evaluated_bar_at: null, last_event_at: null, last_failure_at: null, error_type: null }, subing_ths_alert_15m_v1: { last_evaluated_bar_at: null, last_event_at: null, last_failure_at: '2026-09-04T01:05:00Z', error_type: 'evaluation_failed' } } }, runtimeUnavailable: false })
  assert.match(model.facts[0].value, /未启用/)
  assert.match(model.facts[1].value, /评估失败/)
  assert.equal(model.facts[2].value, '全局尚无已评估 Bar')
  assert.equal(model.facts[3].value, '当前已读取窗口无已保存 Event；不代表中性信号')
  assert.equal(model.history.length, 0)
})

test('does not call a disabled or degraded Runtime globally normal when the Rule has no error', () => {
  for (const status of ['disabled', 'degraded']) {
    const model = buildSubingDetailViewModel({ identity, header, events: [], alertUnavailable: false, rule: { ruleCode: 'subing_ths_alert_15m_v1', displayName: '苏冰预警', symbol: 'jm', frequency: '15m', enabled: true, enabledFrequencies: ['15m'] }, ruleUnavailable: false, runtime: { status, enabled_rule_count: 1, rule_status: { htdy_original_15m: { last_evaluated_bar_at: null, last_event_at: null, last_failure_at: null, error_type: null }, subing_ths_alert_15m_v1: { last_evaluated_bar_at: event.bar_end, last_event_at: null, last_failure_at: null, error_type: null } } }, runtimeUnavailable: false })
    assert.doesNotMatch(model.facts[1]!.value, /全局正常/)
    assert.match(model.facts[1]!.value, status === 'disabled' ? /未启用/ : /状态异常/)
  }
})
