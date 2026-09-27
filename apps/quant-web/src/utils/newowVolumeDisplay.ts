import type { NewowProductChartModel } from '../components/market/detail/newow/newowProductChartPrimitives.ts'

export interface NewowVolumeScore {
  actionId: string
  kind: 'BUILD' | 'CLEAR'
  reference: number
  averageVolume: number
  volumeRatio: number
  bodyRatio: number
  penetrationRatio: number
  volumeScore: number
  bodyScore: number
  penetrationScore: number
  total: number
}
/** Public-page ratios only; candidate scoring does not create an action. */
export function newowBarBreakoutScore(model: NewowProductChartModel, index: number, kind: 'BUILD' | 'CLEAR'): Omit<NewowVolumeScore, 'actionId' | 'kind'> | null {
  const bar = model.bars[index]
  if (!bar || index < 9) return null
  const window = model.bars.slice(index - 9, index + 1)
  if (window.some(item => item.physicalContract !== bar.physicalContract
    || item.segmentId !== bar.segmentId || item.calculationSegmentId !== bar.calculationSegmentId)) return null
  const averageVolume = window.reduce((sum, item) => sum + item.volume, 0) / 10
  const volumeRatio = averageVolume > 0 ? bar.volume / averageVolume : 1
  const bodyRatio = Math.abs(bar.close - bar.open) / Math.max(bar.high - bar.low, 0.001)
  const volumeScore = volumeRatio >= 1.5 ? 2 : volumeRatio >= 1 ? 1 : 0
  const bodyScore = bodyRatio > 0.6 ? 2 : bodyRatio > 0.3 ? 1 : 0
  const reference = kind === 'CLEAR' ? Math.max(...window.map(item => item.high)) : Math.min(...window.map(item => item.low))
  if (reference <= 0) return null
  const penetrationRatio = Math.abs(bar.close - reference) / reference
  const penetrationScore = penetrationRatio > 0.03 ? 2 : penetrationRatio > 0.01 ? 1 : 0
  return { reference, averageVolume, volumeRatio, bodyRatio, penetrationRatio,
    volumeScore, bodyScore, penetrationScore, total: volumeScore + bodyScore + penetrationScore }
}
/** Shared page decoration and explanation; never changes strategy facts. */
export function newowVolumeScores(model: NewowProductChartModel, index: number): readonly NewowVolumeScore[] {
  const bar = model.bars[index]
  if (!bar) return []
  return model.actions.filter(action => action.barEnd === bar.barEnd
    && action.physicalContract === bar.physicalContract && action.segmentId === bar.segmentId
    && action.tradeEligibility === 'ELIGIBLE').flatMap(action => {
    const score = newowBarBreakoutScore(model, index, action.kind)
    return score ? [{ actionId: action.id, kind: action.kind, ...score }] : []
  })
}
/** Page-only color decoration from Niuwa's public scoreBar; no signal or return changes. */
export function newowVolumeColors(model: NewowProductChartModel, up: string, down: string): readonly string[] {
  return model.bars.map((bar, index) => newowVolumeScores(model, index).some(score => score.total >= 4)
    ? 'rgba(255,215,0,0.7)' : bar.close >= bar.open ? up : down)
}
