import type { NewowProductStrategy, NewowReferenceTrade } from '../types/newowProduct.ts'
import type { KlineReferenceCallout } from '../types/referenceCallout.ts'
import { referencePercentDisplay } from './newowDetailPresentation.ts'

/** Decorate only an exact, closed reference trade; never infer pairing or calculate PnL. */
export function newowActionReturnDisplay(
  callout: KlineReferenceCallout,
  strategy: NewowProductStrategy,
  trades: readonly NewowReferenceTrade[],
): { text: string; direction: 'up' | 'down' | 'neutral' } {
  const price = callout.detail.replace('参考价 ', callout.above ? '' : '建仓价:')
  if (!callout.above) return { text: price, direction: 'neutral' }
  const matches = trades.filter(trade => trade.status === 'CLOSED'
    && trade.strategy_code === strategy && trade.exit_signal_id === callout.id
    && trade.physical_contract === callout.physicalContract && trade.exit_bar_end === callout.time
    && trade.exit_reference_price === callout.price)
  if (matches.length !== 1) return { text: price, direction: 'neutral' }
  const result = referencePercentDisplay(matches[0]!.reference_return_pct)
  return result.text === '—' ? { text: price, direction: 'neutral' }
    : { text: `${price}(${result.text})`, direction: result.direction }
}

/** Entry-linked interruption badges never borrow a later exit or imply a closed return. */
export function newowActionStatus(callout: KlineReferenceCallout, strategy: NewowProductStrategy, trades: readonly NewowReferenceTrade[]): string | null {
  if (callout.above) return null
  const matches = trades.filter(trade => trade.strategy_code === strategy
    && trade.entry_signal_id === callout.id && trade.entry_bar_end === callout.time
    && trade.physical_contract === callout.physicalContract && trade.entry_reference_price === callout.price)
  if (matches.length !== 1) return null
  return matches[0]!.status === 'ROLLOVER_INTERRUPTED' ? '换月中断'
    : matches[0]!.status === 'DATA_INTERRUPTED' ? '数据中断' : null
}
