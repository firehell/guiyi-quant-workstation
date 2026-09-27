import assert from 'node:assert/strict'
import test from 'node:test'
import type { NewowDecisionV2 } from '../src/types/newowDecisionV2'
import { buildStatusCard, statusPriceProgress } from '../src/utils/newowStatusCardPresentation.ts'
const price = (raw: string, physical_contract = 'JM2701') => ({ raw, display_value:raw, physical_contract, segment_id:'owner', calculation_segment_id:'quality', frequency:'1d' as const, bar_end:'2026-09-24T07:00:00Z', source_identity:'s', source_category:'canonical_channel' })
const decision = (w = 'hold', d = 'hold', overrides = {}) => ({ cdv2:{ as_of:'2026-09-24T07:00:00Z', trend_bias:'bullish', reference_exposure_range:'0%–10%', reference_exposure_cap:10, facts:['trend_week','trend_day','oscillation_week','oscillation_day'].map(role=>({role,state:role.endsWith('week')?w:d,status:'ready',frequency:role.endsWith('week')?'1w':'1d',bar_end:'2026-09-24T07:00:00Z',physical_contract:'JM2701',segment_id:'owner',age:2})), ...overrides }, prices:{as_of:'2026-09-24T07:00:00Z',current_price:price('51.33'),status_card:{target:price('52.88'),absorb:price('47.96')}} }) as unknown as NewowDecisionV2

test('public screenshot percentages, defensive reversal and Decimal bounds',()=>{
 const p = decision().prices!
 const up = statusPriceProgress(p,'bullish')!
 assert.equal(up.leftLabel,'吸筹'); assert.equal(up.rightLabel,'目标')
 assert.equal(up.leftStatistic,'+7.0%'); assert.equal(up.rightStatistic,'2.9%'); assert.equal(up.progress,'68.5')
 const down = statusPriceProgress(p,'warning')!
 assert.equal(down.leftLabel,'目标'); assert.equal(down.rightLabel,'吸筹')
 assert.equal(down.leftStatistic,'-2.9%'); assert.equal(down.rightStatistic,'7.0%'); assert.equal(down.progress,'31.5')
 p.current_price = price('60'); assert.equal(statusPriceProgress(p,'bullish')?.progress,'100.0'); assert.match(statusPriceProgress(p,'bullish')!.rightStatistic,/^-/)
 p.current_price = price('40'); assert.equal(statusPriceProgress(p,'bullish')?.progress,'0.0')
 p.status_card.target = price('47.96'); p.current_price = price('47.96'); assert.equal(statusPriceProgress(p,'bullish')?.progress,'0.0')
 assert.equal(statusPriceProgress(p,'bearish')?.leftStatistic,'-0.0%')
 p.status_card.target = price('0'); assert.equal(statusPriceProgress(p,'bullish'),null)
 p.status_card.target = price('52.88','JM2609'); assert.equal(statusPriceProgress(p,'bullish'),null)
 assert.equal(statusPriceProgress(decision().prices!,'unknown'),null)
 const exact=decision().prices!; exact.current_price=price('9999999999999999.005'); exact.status_card.target=price('9999999999999999.010'); exact.status_card.absorb=price('9999999999999999.000')
 assert.equal(statusPriceProgress(exact,'bullish')?.progress,'50.0')
 for(const v of [exact.current_price,exact.status_card.target!,exact.status_card.absorb!]) v.segment_id=''
 assert.equal(statusPriceProgress(exact,'bullish'),null)
})
test('16 original trend pairs have distinct presentation, unified exposure, bearish guard and missing fail closed',()=>{
 const names=['上涨启动','震荡上涨','趋势回调','筑底反弹','上涨中继','上涨趋势','高位震荡','高位震荡','震荡反弹','震荡反弹','下跌趋势','震荡下跌','筑底反转','筑底反弹','震荡下跌','震荡下跌']
 let i=0
 for(const w of ['buy','hold','sell','wait']) for(const d of ['buy','hold','sell','wait']) {
  const card=buildStatusCard(decision(w,d),'trend'); assert.equal(card.name,names[i++]); assert.equal(card.exposure,'0%–10%')
 }
 const bear=buildStatusCard(decision('buy','buy',{trend_bias:'bearish',reference_exposure_cap:0,reference_exposure_range:''}),'trend')
 assert.doesNotMatch(bear.advice,/加仓|建仓/); assert.equal(bear.exposure,'0%')
 const missing=decision(); missing.cdv2.facts[0].status='unavailable'; missing.cdv2.facts[0].state=null
 assert.equal(buildStatusCard(missing,'trend').name,'日周状态不足'); assert.equal(buildStatusCard(missing,'trend').risk,'unknown')
 assert.equal(buildStatusCard(null,'trend').progress,null)
 const emptySegment=decision(); emptySegment.cdv2.facts[0]!.segment_id=''
 assert.equal(buildStatusCard(emptySegment,'trend').risk,'unknown')
 const otherPrices=decision(); for(const v of [otherPrices.prices!.current_price,otherPrices.prices!.status_card.target!,otherPrices.prices!.status_card.absorb!]) v.physical_contract='RB2701'
 assert.equal(buildStatusCard(otherPrices,'trend').progress,null)
})
test('oscillation preserves cleared vs idle and excludes hourly even when provided',()=>{
 const a=decision('buy','sell'); const card=buildStatusCard(a,'oscillation')
 assert.equal(card.name,'高位震荡'); assert.equal(card.day.label,'已清仓')
 a.cdv2.facts.push({...a.cdv2.facts[0]!,role:'oscillation_m60',state:'buy'})
 assert.equal(buildStatusCard(a,'oscillation').name,card.name)
 assert.equal(buildStatusCard(decision('wait','wait'),'oscillation').name,'震荡观望')
 assert.equal(buildStatusCard(decision('hold','wait'),'oscillation').name,'震荡整理')
 assert.equal(buildStatusCard(decision(),'main_rise').risk,'unknown')
 const expected=['震荡上涨','高位震荡','震荡整理','震荡反弹','震荡下跌','震荡观望','震荡试盘','震荡离场','震荡观望']
 let i=0
 for(const w of ['hold','sell','wait']) for(const d of ['hold','sell','wait']) assert.equal(buildStatusCard(decision(w,d),'oscillation').name,expected[i++])
})
