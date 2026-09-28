import assert from 'node:assert/strict'
import test from 'node:test'
import type { Cdv2 } from '../src/types/newowDecisionV2'
import { decisionFactAge, decisionFactState, decisionMismatchReason, decisionResonanceReason, decisionTier, decisionDisplay, decisionVolatility } from '../src/utils/newowDecisionV2Presentation.ts'

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

test('certainty tiers preserve source boundaries and do not scale daily weekly totals', () => {
  assert.equal(decisionTier(80).label, '高确定性')
  assert.equal(decisionTier(78).label, '中等确定性')
  assert.equal(decisionTier(60).label, '中等确定性')
  assert.equal(decisionTier(59).label, '低确定性')
  assert.equal(decisionTier(40).label, '低确定性')
  assert.equal(decisionTier(39).label, '信号不足')
  assert.equal(decisionTier(Number.NaN).label, '评分不可用')
})

test('resonance dots and mismatch copy describe server codes without rejudging them', () => {
  const base = { total: 54, action: '减仓观望', action_code: 'warning-bearish', resonance: 'R1', trend_bias: 'warning', oscillation_bias: 'bearish', mismatch: null, reference_exposure_cap: 0, reference_exposure_range: '', scores: { trend: 24, oscillation: 22, resonance: 4, direction: 12, volatility: -8 }, trend_state: { week: 'down', day: 'up' }, facts: [] } as unknown as Cdv2
  const names = ['数据不足', '信号背离', '错配预警', '基调共振', '双螺旋共振']
  for (const [i, n] of [0, 1, 2, 3, 5].entries()) {
    const view = decisionDisplay({ ...base, resonance: 'R' + i })
    assert.equal(view.resonance.name, names[i])
    assert.equal(view.resonance.dots, '●'.repeat(n) + '○'.repeat(5 - n))
  }
  assert.equal(decisionDisplay(base).exposure, '0%')
  for (const mismatch of ['MM1', 'MM2', 'MM3', 'MM4']) {
    const view = decisionDisplay({ ...base, mismatch, mismatch_age: 0 })
    assert.match(view.mismatch!.detail, mismatch === 'MM3' || mismatch === 'MM4' ? /最新一根日K/ : /日线/)
  }
  assert.equal(decisionDisplay({ ...base, mismatch: 'unexpected' }).mismatch, null)
  assert.match(decisionDisplay(base).direction.text, /周线下跌中的反弹/)
  assert.equal(decisionDisplay(base).scores.length, 5)
})

test('volatility uses reported rounded level, remains missing and clamps only the visual dot', () => {
  assert.equal(decisionVolatility({ volatility_pct: null } as Cdv2), null)
  const high = decisionVolatility({ volatility_pct: '6.7', volatility_level: 'high' } as Cdv2)!
  assert.equal(high.label, '高'); assert.equal(high.position, 97); assert.equal(high.value, '6.7')
  const low = decisionVolatility({ volatility_pct: '0.1', volatility_level: 'low' } as Cdv2)!
  assert.equal(low.position, 3)
  assert.equal(decisionVolatility({ volatility_pct: '-1', volatility_level: 'low' } as Cdv2), null)
})

test('minute decision uses a separate completed daily weekly background identity', async () => {
  const { decisionContextIdentity } = await import('../src/utils/newowDecisionV2Presentation.ts')
  for (const frequency of ['5m', '15m', '30m', '60m'] as const) {
    const context = decisionContextIdentity({ product: 'rb', strategy: 'trend', frequency })
    assert.equal(context.background, true)
    assert.equal(context.identity.frequency, '1d')
  }
  assert.equal(decisionContextIdentity({ product: 'rb', strategy: 'trend', frequency: '1w' }).identity.frequency, '1w')
})
