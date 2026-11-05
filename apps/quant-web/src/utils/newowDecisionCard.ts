/** Detail v3.4.49 presentation only. Never produces strategy or account actions. */
import type { Cdv2 } from '../types/newowDecisionV2'
import type { DecisionBasis } from './newowBasisDecision'
import { decisionDisplay } from './newowDecisionV2Presentation.ts'

export const NEWOW_DECISION_CARD_VERSION = 'newow_composite_card_detail3449_v1'
export type DecisionFact = Cdv2['facts'][number]
export const cardState = (fact?: DecisionFact) => fact?.status !== 'ready' ? '状态不可用'
  : fact.state === 'buy' || fact.state === 'hold' ? '持股' : fact.state === 'sell' ? '清仓' : fact.state === 'wait' ? '空仓' : '状态不可用'
export const cardStateColor = (fact?: DecisionFact) => fact?.status !== 'ready' ? '#8e8e93'
  : fact.state === 'buy' || fact.state === 'hold' ? '#ff3b30' : fact.state === 'sell' || fact.state === 'wait' ? '#34c759' : '#8e8e93'
export const cardChipState = (axis: string, fact?: DecisionFact) => fact?.status !== 'ready' || fact.state == null ? '状态不可用'
  : axis === 'oscillation' ? fact.state === 'buy' || fact.state === 'hold' ? '持股' : '清仓'
    : ({buy:'建仓',hold:'持股',sell:'清仓',wait:'空仓'} as Record<string,string>)[fact.state] ?? '状态不可用'
export const cardActionColor = (action: string) => ['建仓','加仓'].includes(action) ? '#ff3b30'
  : ['减仓','清仓','空仓'].includes(action) ? '#34c759' : '#8e8e93'
export function cardChain(cd: Cdv2 | undefined, strategy: string, basis: DecisionBasis, dominant?: string | null) {
  const family = strategy === 'dual' ? dominant : ['trend','oscillation'].includes(strategy) ? strategy : null
  if (!cd || !family) return []
  return (basis === 'day' ? ['day','m60','week'] : ['week','day','m60']).map((period, index) => {
    const fact = cd.facts.find(f => f.role === `${family}_${period}`)
    const state = cardState(fact)
    return { period, label: period === 'week' ? '周线' : period === 'day' ? '日线' : '60分',
      state, color: state === '持股' ? '#ff3b30' : state === '清仓' ? '#34c759' : '#8e8e93',
      fact, main: index === 0, reference: index === 2 }
  })
}
export function cardMergedChain(cells: ReturnType<typeof cardChain>) {
  return cells.length === 3 && cells.every(c => c.state === cells[0]!.state && c.state !== '状态不可用')
    ? `周 / 日 / 60分 均在${cells[0]!.state}（三周期同向）` : null
}
const resonanceCopy: Record<string, string> = {
  R4: '趋势与震荡三周期同向，噪声正交验证通过，结论一致性最高。',
  R3: '趋势与震荡方向一致，但其中一方内部周期不齐，节奏存在分歧。',
  R2: '趋势与震荡方向背离，或趋势缺数据而震荡已明确转向，均属错配期，仅作事件级响应。',
  R1: '趋势内部周/日线已打架，叠加震荡明确表态，为最难判状态，按周线主口径谨慎处理、仅作提示。',
  R0: '趋势或震荡信号缺失，无法判定共振，等待信号明确。',
}
export function cardPresentation(cd: Cdv2) {
  const view = decisionDisplay(cd)
  const w = cd.trend_state?.week, d = cd.trend_state?.day, m = cd.trend_state?.m60
  const direction = w === 'down' && (d === 'up' || m === 'up') ? { text:'从周线开始下跌，当前为周线下跌中的反弹（背离），勿追涨', color:'#ff6b35' }
    : w === 'down' ? { text:'从周线开始下跌（大级别空头确立），必须空仓等待反转', color:'#ff3b30' }
    : w === 'up' && d === 'down' ? { text:'从日线开始下跌（周线未破位，日线回调），等待日线吸筹回踩', color:'#ff9500' }
    : w === 'up' && d === 'up' && m === 'down' ? { text:'60分钟回踩（小级别调整，日/周线向上），看大做小等 60min 吸筹', color:'#ff9500' }
    : w === 'up' && d === 'up' && m === 'up' ? { text:'从60分钟开始上涨（多周期共振向上），顺势建仓', color:'#ff3b30' }
    : { text:'信号不足，观察（等待趋势/震荡信号明确）', color:'#8e8e93' }
  const age = cd.mismatch_age >= 0 ? String(cd.mismatch_age) : '--'
  const cross = cd.mismatch_age === 0 ? '最新一根' : cd.mismatch_age > 0 ? `${age} 根前` : '--'
  const mismatch = !view.mismatch ? null : { ...view.mismatch,
    ageLabel: cd.mismatch === 'MM1' ? `震荡已清 ${age} 根` : cd.mismatch === 'MM2' ? `震荡已持 ${age} 根` : `趋势已转向 ${age} 根`,
    action: ({MM1:'趋势日线仍持股 · 震荡已转空',MM2:'趋势日线仍空仓 · 震荡已建仓',MM3:'趋势已转空 · 震荡仍持股',MM4:'趋势已转多 · 震荡仍空仓'} as Record<string,string>)[cd.mismatch!],
    detail: ({MM1:'趋势日线仍在黄带，未发生下穿',MM2:'趋势日线仍在蓝带，未发生上穿',MM3:`趋势日线 ${cross}下穿 MA10 · 震荡日线仍持有`,MM4:`趋势日线 ${cross}上穿 MA10 · 震荡日线仍处清仓态`} as Record<string,string>)[cd.mismatch!] }
  return { ...view, direction, mismatch, resonance:{...view.resonance, description:resonanceCopy[cd.resonance] ?? '—'},
    position: cd.reference_exposure_cap > 0 ? `建议仓位 ${view.exposure.replaceAll('–','-')}` : '',
    volatility: view.volatility ? {...view.volatility,value:String(Number(view.volatility.value))} : null }
}
