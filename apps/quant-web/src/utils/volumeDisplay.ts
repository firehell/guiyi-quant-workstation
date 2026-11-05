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
