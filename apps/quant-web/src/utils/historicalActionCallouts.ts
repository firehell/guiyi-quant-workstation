import type { BarData } from '../types/market.ts'
import type { HistoricalChartAction } from '../types/historicalChartAction.ts'
import type { KlineReferenceCallout } from '../types/referenceCallout.ts'
import { newowReferencePrice } from './newowPagePresentation.ts'
import { referencePercentDisplay } from './newowDetailPresentation.ts'

/** Formatting only. The server owns role, trade pairing, direction and return. */
export function historicalActionCallouts(actions: readonly HistoricalChartAction[], bars: readonly BarData[]): KlineReferenceCallout[] {
  const owned = new Map(bars.map(bar => [`${Date.parse(bar.time)}|${bar.physicalContract}`, bar]))
  const unique = new Map<string, KlineReferenceCallout>()
  for (const action of actions) {
    const bar = owned.get(`${Date.parse(action.bar_end)}|${action.physical_contract}`)
    if (!bar || bar.calculationSegmentId && bar.calculationSegmentId !== action.calculation_segment_id) continue
    const closing = action.role === 'CLEAR'
    const returns = closing && action.status === 'CLOSED' ? referencePercentDisplay(action.return_pct) : { text: '—', direction: 'neutral' as const }
    const interrupted = !closing && action.status === 'ROLLOVER_INTERRUPTED' ? ' · 换月中断'
      : !closing && action.status === 'DATA_INTERRUPTED' ? ' · 数据中断' : ''
    const price = newowReferencePrice(action.reference_price)
    unique.set(action.action_id, {
      id: action.action_id, time: action.bar_end, physicalContract: action.physical_contract, price: action.reference_price,
      title: `${closing ? '清仓' : '建仓'}·${action.side === 'LONG' ? '多' : '空'}${interrupted}`,
      detail: closing ? `${price}${returns.text === '—' ? '' : `(${returns.text})`}` : `建仓价:${price}`,
      tone: returns.direction === 'up' ? 'gain' : returns.direction === 'down' ? 'loss' : 'neutral', above: closing,
    })
  }
  return [...unique.values()]
}
