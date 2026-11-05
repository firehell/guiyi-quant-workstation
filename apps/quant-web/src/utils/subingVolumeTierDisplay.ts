import { validVolume, type DisplayVolumeBar } from './volumeDisplay.ts'

/** Display extension to all SuBing chart periods; never changes the research factor or alerts. */
export const SUBING_VOLUME_TIER_DISPLAY_VERSION = 'subing_volume_tier_display_v1'
export interface SubingVolumeTierPoint {
  bar: DisplayVolumeBar
  tier: 2 | 3
  ratio: number
  previousEnd: string
}
export function subingVolumeTierPoints(bars: readonly DisplayVolumeBar[], breaks: readonly { time: string }[] = []): SubingVolumeTierPoint[] {
  const interruptions = breaks.map(item => Date.parse(item.time))
  return bars.flatMap((bar, index) => {
    const previous = bars[index - 1]
    if (!previous || !validVolume(bar) || !validVolume(previous) || previous.volume <= 0
      || bar.confirmed === false || previous.confirmed === false
      || !bar.physicalContract || bar.physicalContract !== previous.physicalContract
      || !bar.calculationSegmentId || bar.calculationSegmentId !== previous.calculationSegmentId
      || bar.segmentId !== previous.segmentId) return []
    const start = Date.parse(previous.time), end = Date.parse(bar.time)
    if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start
      || interruptions.some(time => time >= start && time <= end)) return []
    const tier = bar.volume >= previous.volume * 3 ? 3 : bar.volume >= previous.volume * 2 ? 2 : null
    const ratio = bar.volume / previous.volume
    return tier && Number.isFinite(ratio) ? [{ bar, tier, ratio, previousEnd: previous.time }] : []
  })
}
