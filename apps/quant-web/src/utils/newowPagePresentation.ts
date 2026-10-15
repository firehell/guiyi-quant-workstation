import { formatDecimalText, formatMarketPercent } from './marketDisplay.ts'

/** Display-only: source prices and returns keep their original precision. */
export const newowReferencePrice = (raw: string | null | undefined) =>
  formatDecimalText(raw, { maximumFractionDigits: 2, minimumFractionDigits: 2 })

export function newowSimpleDualLabel(_origin: 'trend' | 'oscillation', above: boolean, price: string) {
  return `${above ? '清仓' : '建仓'} ${newowReferencePrice(price)}`
}

export const newowReferencePercent = (raw: string | null | undefined) => {
  const text = formatDecimalText(raw, { maximumFractionDigits: 2, minimumFractionDigits: 2, signed: true })
  const bound = formatMarketPercent(raw, 'percentage_points', true)
  return bound.startsWith('<') || bound.startsWith('>') ? bound : text === '—' ? text : `${text}%`
}

export function newowReferencePoints(raw: string | null | undefined): string {
  const pct = newowReferencePercent(raw)
  return pct === '—' ? pct : `${pct.slice(0,-1)} 百分点`
}

/** Main-chart coordinates remain numeric; only price-axis text uses fixed precision. */
export const NEWOW_CHART_PRICE_FORMAT = { type: 'price' as const, precision: 2, minMove: 0.01 }
