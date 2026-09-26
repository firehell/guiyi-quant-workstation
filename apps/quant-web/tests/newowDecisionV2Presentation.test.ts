import assert from 'node:assert/strict'
import test from 'node:test'
import type { Cdv2 } from '../src/types/newowDecisionV2'
import { decisionFactAge, decisionFactState, decisionMismatchReason, decisionResonanceReason } from '../src/utils/newowDecisionV2Presentation.ts'

const fact = (overrides = {}) => ({ role: 'trend_day', state: 'buy', age: 0, frequency: '1d', status: 'ready', bar_end: null, physical_contract: null, segment_id: null, source_category: 'canonical_strategy_replay', reason: null, ...overrides })
test('zero age is valid, weekly age has its own unit, unavailable inputs never appear current', () => {
  assert.equal(decisionFactAge(fact()), '0 根日K')
  assert.equal(decisionFactState(fact()), '建仓')
  assert.equal(decisionFactAge(fact({ role: 'trend_week', frequency: '1w', age: 4 })), '4 根周K')
  assert.equal(decisionFactAge(fact({ age: -1 })), '计龄未知')
  assert.equal(decisionFactAge(fact({ status: 'unavailable' })), '计龄未知')
  assert.equal(decisionFactState(fact({ status: 'unavailable' })), '状态不可用')
  assert.equal(decisionFactState(fact({ role: 'trend_m60' })), '未参与')
  assert.equal(decisionFactAge(undefined), '计龄未知')
})
test('reported mismatch explains its actual daily age source and freshness', () => {
  for (const mismatch of ['MM1', 'MM2', 'MM3', 'MM4']) {
    const cd = { mismatch, mismatch_age: mismatch === 'MM1' || mismatch === 'MM2' ? 3 : 0 } as Cdv2
    assert.match(decisionMismatchReason(cd), mismatch === 'MM1' || mismatch === 'MM2' ? /日线震荡最近动作：3 根日K/ : /日线趋势穿越信号：0 根日K/)
    if (mismatch === 'MM2') assert.match(decisionMismatchReason(cd), /趋势基调不是偏空/)
  }
  assert.match(decisionMismatchReason({ mismatch: 'MM3', mismatch_age: -1 } as Cdv2), /计龄未知/)
  assert.match(decisionMismatchReason({ mismatch: null } as Cdv2), /输入缺失时不代表已确认无冲突/)
})
test('R4 is explained as available two-period agreement rather than full three-period confirmation', () => {
  const cd = { resonance: 'R4', trend_bias: 'bullish', oscillation_bias: 'bullish' } as Cdv2
  assert.match(decisionResonanceReason(cd), /趋势基调偏多 · 震荡节奏偏多/)
  assert.match(decisionResonanceReason(cd), /至少两个明确周期同向/)
  assert.match(decisionResonanceReason(cd), /不包含60分钟确认/)
  assert.match(decisionResonanceReason({ ...cd, resonance: 'R2', mismatch: 'MM4' }), /命中 MM4/)
  assert.match(decisionResonanceReason({ ...cd, resonance: 'R1', trend_bias: 'bearish' }), /趋势与震荡方向相反/)
  assert.match(decisionResonanceReason({ ...cd, resonance: 'R1', trend_bias: 'warning' }), /趋势处于谨慎／反弹警示/)
})
