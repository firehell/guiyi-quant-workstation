import type { NewowProductChartModel } from '../components/market/detail/newow/newowProductChartPrimitives.ts'
import { volumeScores } from './volumeDisplay.ts'
/** Public-page reference-line rule retains its original action condition. */
export function newowBarBreakoutScore(model: NewowProductChartModel, index: number, kind: 'BUILD' | 'CLEAR') {
  return volumeScores(model.bars, index).find(score => score.side === (kind === 'BUILD' ? 'lower' : 'upper')) ?? null
}
export function newowActionBreakoutScores(model: NewowProductChartModel, index: number) {
  const bar = model.bars[index]
  if (!bar) return []
  return model.actions.filter(action => action.barEnd === bar.barEnd
    && action.physicalContract === bar.physicalContract && action.segmentId === bar.segmentId
    && action.tradeEligibility === 'ELIGIBLE').flatMap(action => {
    const score = newowBarBreakoutScore(model, index, action.kind)
    return score ? [{ ...score, actionId: action.id, kind: action.kind }] : []
  })
}
