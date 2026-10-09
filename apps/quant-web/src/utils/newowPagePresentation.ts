import { formatDecimalText } from './marketDisplay.ts'

/** Display-only: source prices and returns keep their original precision. */
export const newowReferencePrice = (raw: string | null | undefined) =>
  formatDecimalText(raw, { maximumFractionDigits: 2, minimumFractionDigits: 2 })

export function newowSimpleDualLabel(origin: 'trend' | 'oscillation', above: boolean, price: string) {
  return `${origin === 'trend' ? '趋' : '震'}${above ? '清' : '建'} ${newowReferencePrice(price)}`
}

export const newowReferencePercent = (raw: string | null | undefined) => {
  const text = formatDecimalText(raw, { maximumFractionDigits: 2, minimumFractionDigits: 2, signed: true })
  return text === '—' ? text : `${text}%`
}
