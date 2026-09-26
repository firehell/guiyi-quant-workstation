import type { NewowProductChartModel } from '../components/market/detail/newow/newowProductChartPrimitives.ts'

/** Page-only color decoration from Niuwa's public scoreBar; no signal or return changes. */
export function newowVolumeColors(model: NewowProductChartModel, up: string, down: string): readonly string[] {
  return model.bars.map((bar, index) => {
    const ordinary = bar.close >= bar.open ? up : down
    if (model.identity.strategy !== 'oscillation' || index < 9) return ordinary
    const window = model.bars.slice(index - 9, index + 1)
    if (window.some(item => item.physicalContract !== bar.physicalContract
      || item.segmentId !== bar.segmentId || item.calculationSegmentId !== bar.calculationSegmentId)) return ordinary
    const actions = model.actions.filter(action => action.barEnd === bar.barEnd
      && action.physicalContract === bar.physicalContract && action.segmentId === bar.segmentId
      && action.tradeEligibility === 'ELIGIBLE')
    const average = window.reduce((sum, item) => sum + item.volume, 0) / 10
    const ratio = average > 0 ? bar.volume / average : 1
    const body = Math.abs(bar.close - bar.open) / Math.max(bar.high - bar.low, 0.001)
    const volumeScore = ratio >= 1.5 ? 2 : ratio >= 1 ? 1 : 0
    const bodyScore = body > 0.6 ? 2 : body > 0.3 ? 1 : 0
    const highlighted = actions.some(action => {
      const reference = action.kind === 'CLEAR' ? Math.max(...window.map(item => item.high)) : Math.min(...window.map(item => item.low))
      if (reference <= 0) return false
      const penetration = Math.abs(bar.close - reference) / reference
      return volumeScore + bodyScore + (penetration > 0.03 ? 2 : penetration > 0.01 ? 1 : 0) >= 4
    })
    return highlighted ? 'rgba(255,215,0,0.7)' : ordinary
  })
}
