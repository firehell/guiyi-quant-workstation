import type { BarData } from '../types/market.ts'

export const THS_MACD_DISPLAY_VERSION = 'ths_macd_ma21_display_v1'

/** Owner formula: EMA(12/26/9), SMA21-filtered CROSS, trailing HHV60 offset.
 * Display only; never an AlertEvent or an account/strategy decision.
 * EMA seeds with the first close of each physical/calculation segment.
 */
export function calculateThsMacdDisplay(bars: readonly BarData[]) {
  const dif: { time: string; value: number }[] = []
  const dea: { time: string; value: number }[] = []
  const histogram: { time: string; value: number }[] = []
  const crosses: { time: string; value: number; side: 'golden' | 'death' }[] = []
  let fast = 0, slow = 0, signal = 0
  let previousDif = 0, previousDea = 0
  let closes: number[] = [], amplitudes: number[] = []
  let previous: BarData | undefined
  for (const bar of bars) {
    if (previous && Date.parse(bar.time) <= Date.parse(previous.time)) throw new Error('MACD bar times must increase')
    const reset = !previous || previous.physicalContract !== bar.physicalContract || previous.calculationSegmentId !== bar.calculationSegmentId
    if (reset) { closes = []; amplitudes = [] }
    if (!Number.isFinite(bar.close)) { previous = undefined; closes = []; amplitudes = []; continue }
    fast = closes.length ? fast + (bar.close - fast) * 2 / 13 : bar.close
    slow = closes.length ? slow + (bar.close - slow) * 2 / 27 : bar.close
    const diff = fast - slow
    signal = closes.length ? signal + (diff - signal) * 2 / 10 : diff
    closes.push(bar.close)
    if (closes.length > 21) closes.shift()
    amplitudes.push(Math.max(Math.abs(diff), Math.abs(signal)))
    if (amplitudes.length > 60) amplitudes.shift()
    const offset = Math.max(Math.max(...amplitudes) * 0.12, 0.01)
    const ma21 = closes.reduce((sum, close) => sum + close, 0) / 21
    if (closes.length === 21) {
      if (previousDif <= previousDea && diff > signal && bar.close > ma21) crosses.push({ time: bar.time, value: diff - offset, side: 'golden' })
      if (previousDea <= previousDif && signal > diff && bar.close < ma21) crosses.push({ time: bar.time, value: diff + offset, side: 'death' })
    }
    dif.push({ time: bar.time, value: diff })
    dea.push({ time: bar.time, value: signal })
    histogram.push({ time: bar.time, value: 2 * (diff - signal) })
    previousDif = diff; previousDea = signal; previous = bar
  }
  return { dif, dea, histogram, crosses }
}
