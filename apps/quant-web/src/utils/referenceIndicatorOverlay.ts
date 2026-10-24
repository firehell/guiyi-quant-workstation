import type { BarData } from '../types/market'
import type { KlineReferenceIndicator } from '../types/referenceCallout'

// An absent/failed/out-of-window reference read must not erase chart indicators.
// Explicit null values on matching reference Bars still preserve warm-up gaps.
export function referenceIndicatorOverlay(bars: readonly BarData[], points?: readonly KlineReferenceIndicator[]) {
  if (!points?.length) return null
  const byIdentity = new Map(points.map(point => [`${Date.parse(point.bar_end)}:${point.physical_contract}`, point]))
  const exact = bars.flatMap(bar => {
    const point = byIdentity.get(`${Date.parse(bar.time)}:${bar.physicalContract ?? ''}`)
    return point ? [{ time: bar.time, point }] : []
  })
  if (!exact.length) return null
  const values = (key: 'dif' | 'dea' | 'macd' | 'ema21') => exact.map(({ time, point }) => ({ time, value: point[key] === null ? Number.NaN : Number(point[key]) }))
  return { ema21: values('ema21'), dif: values('dif'), dea: values('dea'), histogram: values('macd') }
}
