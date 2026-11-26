/** Strategy-independent display scoring. Never creates signals or changes market facts. */
export const VOLUME_DISPLAY_VERSION = 'guiyi_volume_display_v1'
export interface VolumeBar {
  open: number; high: number; low: number; close: number; volume?: number | null
  physicalContract?: string; segmentId?: string; calculationSegmentId?: string
  confirmed?: boolean
}
export interface DisplayVolumeBar extends VolumeBar { time: string; tradingDay?: string; trading_day?: string }
export interface VolumeScore {
  side: 'lower' | 'upper'; reference: number; averageVolume: number
  volumeRatio: number; bodyRatio: number; penetrationRatio: number
  volumeScore: number; bodyScore: number; penetrationScore: number; total: number
}
export const VOLUME_SCALE_OPTIONS = { scaleMargins: { top: 0.87, bottom: 0 }, visible: false }
export function validVolume(bar: VolumeBar): bar is VolumeBar & { volume: number } {
  return typeof bar.volume === 'number' && Number.isFinite(bar.volume) && bar.volume >= 0
}
export function volumeScores(bars: readonly VolumeBar[], index: number): readonly VolumeScore[] {
  const bar = bars[index]
  if (!bar || index < 9 || bar.confirmed === false || !bar.physicalContract || !bar.calculationSegmentId) return []
  const window = bars.slice(index - 9, index + 1)
  if (window.some(item => item.confirmed === false || !validVolume(item)
    || ![item.open, item.high, item.low, item.close].every(Number.isFinite) || item.high < item.low
    || item.physicalContract !== bar.physicalContract || item.segmentId !== bar.segmentId
    || item.calculationSegmentId !== bar.calculationSegmentId)) return []
  const averageVolume = window.reduce((sum, item) => sum + item.volume!, 0) / 10
  const volumeRatio = averageVolume > 0 ? bar.volume! / averageVolume : 1
  const bodyRatio = Math.abs(bar.close - bar.open) / Math.max(bar.high - bar.low, 0.001)
  const volumeScore = volumeRatio >= 1.5 ? 2 : volumeRatio >= 1 ? 1 : 0
  const bodyScore = bodyRatio > 0.6 ? 2 : bodyRatio > 0.3 ? 1 : 0
  return (['lower', 'upper'] as const).flatMap(side => {
    const reference = side === 'upper' ? Math.max(...window.map(item => item.high)) : Math.min(...window.map(item => item.low))
    if (reference <= 0) return []
    const penetrationRatio = Math.abs(bar.close - reference) / reference
    const penetrationScore = penetrationRatio > 0.03 ? 2 : penetrationRatio > 0.01 ? 1 : 0
    return [{ side, reference, averageVolume, volumeRatio, bodyRatio, penetrationRatio,
      volumeScore, bodyScore, penetrationScore, total: volumeScore + bodyScore + penetrationScore }]
  })
}
export function volumeColors(bars: readonly VolumeBar[], theme: 'light' | 'dark' = 'light', scoring = true): readonly string[] {
  return bars.map((bar, index) => scoring && volumeScores(bars, index).some(score => score.total >= 4)
    ? theme === 'dark' ? '#FFD60A' : '#D9A400'
    : bar.close >= bar.open ? 'rgba(255,59,48,0.6)' : 'rgba(52,199,89,0.6)')
}

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

export type VolumePolicy = 'generic' | 'subing' | 'newow'

/** Keep the selected look separate from completed-bar facts and any strategy volume condition. */
export function volumePresentation(
  policy: VolumePolicy,
  bars: readonly DisplayVolumeBar[],
  options: {
    theme?: 'light' | 'dark'
    enabled: boolean
    allowTiers?: boolean
    breaks?: readonly { time: string }[]
  },
) {
  const { theme, enabled, allowTiers, breaks } = options
  return {
    colors: volumeColors(bars, theme, enabled && policy !== 'subing'),
    tiers: enabled && policy === 'subing' && allowTiers ? subingVolumeTierPoints(bars, breaks) : [],
  }
}
