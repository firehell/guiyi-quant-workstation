import type {
  NewowProductDisplayState,
  NewowProductSection,
  NewowProductSectionResponse,
  NewowResourceLifecycle,
} from '../types/newowProduct.ts'

export interface NewowProductSectionViewModel {
  readonly section: NewowProductSection
  readonly state: NewowProductDisplayState
  readonly reasonCode: string | null
  readonly staleReadAt: string | null
}

export function buildNewowProductSectionViewModel(input: {
  readonly section: NewowProductSection
  readonly response: NewowProductSectionResponse | null
  readonly lifecycle: NewowResourceLifecycle
}): NewowProductSectionViewModel {
  let state: NewowProductDisplayState = input.lifecycle
  if (input.lifecycle === 'ready' && input.response !== null) {
    if (input.response.status.status !== 'ready') state = input.response.status.status
    else if (input.section === 'chart' && input.response.section === 'chart' && input.response.value?.actions.length === 0) state = 'no_action'
    else if (input.section === 'reference' && input.response.section === 'reference' && input.response.value?.summary.closed_count === 0) state = 'empty_closed'
  }
  return {
    section: input.section,
    state,
    reasonCode: input.response?.status.reason_code ?? null,
    staleReadAt: input.lifecycle === 'stale' ? input.response?.meta.read_at ?? null : null,
  }
}

/** Format the server Decimal lexeme without converting it to a binary number. */
export function formatDecimalString(value: string | null, fractionDigits?: number): string {
  if (value === null) return '—'
  const expanded = expandExponent(value)
  const sign = expanded.startsWith('-') ? '-' : expanded.startsWith('+') ? '+' : ''
  const unsigned = sign ? expanded.slice(1) : expanded
  let [whole, fraction = ''] = unsigned.split('.')
  whole = whole || '0'
  if (fractionDigits !== undefined) {
    if (!Number.isInteger(fractionDigits) || fractionDigits < 0 || fractionDigits > 100) throw new Error('fractionDigits is invalid')
    fraction = fraction.slice(0, fractionDigits).padEnd(fractionDigits, '0')
  }
  const grouped = whole.replace(/\B(?=(\d{3})+(?!\d))/g, ',')
  return `${sign}${grouped}${fraction.length ? `.${fraction}` : ''}`
}

function expandExponent(value: string): string {
  const match = /^([+-]?)(\d*\.?\d*)[eE]([+-]?\d+)$/.exec(value)
  if (match === null) return value
  const sign = match[1]!
  const mantissa = match[2]!
  const exponent = Number(match[3])
  if (!Number.isSafeInteger(exponent) || Math.abs(exponent) > 10000) throw new Error('Decimal exponent is invalid')
  const [whole = '', fraction = ''] = mantissa.split('.')
  const digits = `${whole}${fraction}` || '0'
  const point = whole.length + exponent
  if (point <= 0) return `${sign}0.${'0'.repeat(-point)}${digits}`
  if (point >= digits.length) return `${sign}${digits}${'0'.repeat(point - digits.length)}`
  return `${sign}${digits.slice(0, point)}.${digits.slice(point)}`
}
