import type { ExperimentBar } from './newowExperiments.ts'
import type { DisplayVolumeBar, VolumeBar } from './volumeDisplay.ts'
export interface ExperimentVolumeSource extends VolumeBar {
  barEnd: string; segmentId: string; calculationSegmentId: string
}
/** Experiment segments are calculation segments; join only the exact source owner and OHLC. */
export function experimentVolumeBars(bars: readonly ExperimentBar[], source: readonly ExperimentVolumeSource[]): DisplayVolumeBar[] {
  const byTime = new Map(source.map(bar => [`${Date.parse(bar.barEnd)}:${bar.physicalContract}`, bar]))
  return bars.map(bar => {
    const input = byTime.get(`${Date.parse(bar.bar_end)}:${bar.physical_contract}`)
    const sameSource = input && bar.calculation_segment_id === input.calculationSegmentId
      && (bar.segment_id === input.segmentId || bar.segment_id === input.calculationSegmentId)
      && (['open','high','low','close'] as const).every(key => Number(bar[key]) === input[key])
    return { time: bar.bar_end, tradingDay: bar.trading_day, physicalContract: bar.physical_contract,
      segmentId: input && sameSource ? input.segmentId : bar.segment_id,
      calculationSegmentId: bar.calculation_segment_id,
      open: Number(bar.open), high: Number(bar.high), low: Number(bar.low), close: Number(bar.close),
      volume: sameSource ? input.volume : undefined, confirmed: input?.confirmed }
  })
}
