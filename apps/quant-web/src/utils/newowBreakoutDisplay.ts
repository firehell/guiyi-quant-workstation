import type { NewowProductChartModel } from '../components/market/detail/newow/newowProductChartPrimitives.ts'
import { newowBarBreakoutScore, newowVolumeScores } from './newowVolumeDisplay.ts'

export const NEWOW_BREAKOUT_DISPLAY_VERSION = 'newow_oscillation_breakout_line_page_v1'
export interface NewowBreakoutDisplay {
  readonly version: typeof NEWOW_BREAKOUT_DISPLAY_VERSION
  readonly barEnd: string
  readonly price: number
  readonly origin: 'clear_action' | 'high_touch'
  readonly score: NonNullable<ReturnType<typeof newowBarBreakoutScore>>
  readonly confirmScore: 0 | 1
  readonly displayScore: number
}

/** Public _updateBreakoutLines display selection, scoped to the latest futures owner.
 * Does not output a StrategyAction or participate in ReferenceTrade/performance.
 */
export function newowOscillationBreakout(model: NewowProductChartModel): NewowBreakoutDisplay | null {
  if (model.identity.strategy !== 'oscillation') return null
  const last = model.bars.at(-1)
  if (!last) return null
  const sameOwner = (index: number) => {
    const bar = model.bars[index]
    return !!bar && bar.physicalContract === last.physicalContract && bar.segmentId === last.segmentId
      && bar.calculationSegmentId === last.calculationSegmentId
  }
  let latest: { index: number; price: number; origin: NewowBreakoutDisplay['origin']; score: NewowBreakoutDisplay['score'] } | null = null
  for (let index = model.bars.length - 1; index >= 0 && sameOwner(index); index--) {
    const score = newowVolumeScores(model, index).find(item => item.kind === 'CLEAR' && item.total >= 4)
    const action = score && model.actions.find(item => item.id === score.actionId)
    if (score && action) { latest = { index, price: action.value, origin: 'clear_action', score }; break }
  }
  for (let index = model.bars.length - 1; index >= Math.max(0, model.bars.length - 50) && sameOwner(index); index--) {
    const score = newowBarBreakoutScore(model, index, 'CLEAR')
    const bar = model.bars[index]!
    if (score && bar.high >= score.reference && score.total >= 4) {
      // A same-date event retains its server reference price; the raw candidate uses close.
      if (!latest || index > latest.index) latest = { index, price: bar.close, origin: 'high_touch', score }
      break
    }
  }
  if (!latest || !Number.isFinite(latest.price) || last.close <= 0
    || latest.price < last.close * 0.01 || latest.price > last.close * 50) return null
  let confirmScore: 0 | 1 = 0
  for (let offset = 1; offset <= 2; offset++) {
    const index = latest.index + offset
    if (!sameOwner(index)) break
    const score = newowBarBreakoutScore(model, index, 'CLEAR')
    if (score && model.bars[index]!.close > score.reference) { confirmScore = 1; break }
  }
  return { version: NEWOW_BREAKOUT_DISPLAY_VERSION, barEnd: model.bars[latest.index]!.barEnd,
    price: latest.price, origin: latest.origin, score: latest.score, confirmScore, displayScore: latest.score.total + confirmScore }
}
