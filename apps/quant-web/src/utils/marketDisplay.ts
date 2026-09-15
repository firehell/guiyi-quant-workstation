import type { MarketFrequency } from '../types/market.ts'

const DECIMAL_TEXT = /^([+-]?)(?:(\d+)(?:\.(\d*))?|\.(\d+))(?:[eE]([+-]?\d+))?$/
const SHANGHAI_TIME_ZONE = 'Asia/Shanghai'

const FREQUENCY_LABELS: Record<MarketFrequency, string> = {
  '1m': '1分钟',
  '5m': '5分钟',
  '15m': '15分钟',
  '30m': '30分钟',
  '60m': '60分钟',
  '1d': '日线',
  '1w': '周线',
}

interface ParsedDecimal { negative: boolean; digits: string; scale: number }
export interface DecimalDisplayOptions {
  maximumFractionDigits?: number
  minimumFractionDigits?: number
  grouping?: boolean
  signed?: boolean
}

/** Display-only Decimal rounding. Source lexemes never pass through binary Number arithmetic. */
export function formatDecimalText(
  value: string | null | undefined,
  options: DecimalDisplayOptions = {},
): string {
  const parsed = parseDecimal(value)
  if (!parsed) return '—'
  const maximum = options.maximumFractionDigits ?? 4
  const minimum = options.minimumFractionDigits ?? 0
  if (!Number.isInteger(maximum) || !Number.isInteger(minimum) || minimum < 0 || maximum < minimum || maximum > 100) {
    throw new Error('Decimal display precision is invalid')
  }
  const rounded = roundedMagnitude(parsed, maximum)
  const padded = rounded.toString().padStart(maximum + 1, '0')
  let whole = maximum === 0 ? padded : padded.slice(0, -maximum)
  let fraction = maximum === 0 ? '' : padded.slice(-maximum)
  while (fraction.length > minimum && fraction.endsWith('0')) fraction = fraction.slice(0, -1)
  if (options.grouping) whole = whole.replace(/\B(?=(\d{3})+(?!\d))/g, ',')
  const sign = rounded === 0n ? '' : parsed.negative ? '-' : options.signed ? '+' : ''
  return `${sign}${whole}${fraction ? `.${fraction}` : ''}`
}

/** Calculated/reference prices use at most four display decimals. */
export function formatMarketDecimal(value: string | null | undefined): string {
  return formatDecimalText(value, { maximumFractionDigits: 4 })
}

export function formatMarketPercent(
  value: string | null | undefined,
  unit: 'ratio' | 'percentage_points',
  signed = false,
): string {
  const parsed = parseDecimal(value)
  if (!parsed) return '—'
  const percentage = unit === 'ratio' ? multiplyByPowerOfTen(parsed, 2) : parsed
  if (!isZero(percentage) && isLessThanHundredth(percentage)) {
    return percentage.negative ? '>-0.01%' : '<0.01%'
  }
  const text = formatParsedDecimal(percentage, { maximumFractionDigits: 2, signed })
  return text === '—' ? text : `${text}%`
}

function parseDecimal(value: string | null | undefined): ParsedDecimal | null {
  const raw = value?.trim()
  if (!raw || raw.length > 10_000) return null
  const match = DECIMAL_TEXT.exec(raw)
  if (!match) return null
  const exponent = Number(match[5] ?? '0')
  if (!Number.isSafeInteger(exponent) || Math.abs(exponent) > 10_000) return null
  const whole = match[2] ?? ''
  const fraction = match[3] ?? match[4] ?? ''
  let digits = `${whole}${fraction}`.replace(/^0+(?=\d)/, '') || '0'
  let scale = fraction.length - exponent
  if (scale < 0) {
    digits += '0'.repeat(-scale)
    scale = 0
  }
  return { negative: match[1] === '-' && !/^0+$/.test(digits), digits, scale }
}

function formatParsedDecimal(parsed: ParsedDecimal, options: DecimalDisplayOptions): string {
  const maximum = options.maximumFractionDigits ?? 4
  const minimum = options.minimumFractionDigits ?? 0
  const rounded = roundedMagnitude(parsed, maximum)
  const padded = rounded.toString().padStart(maximum + 1, '0')
  let whole = maximum === 0 ? padded : padded.slice(0, -maximum)
  let fraction = maximum === 0 ? '' : padded.slice(-maximum)
  while (fraction.length > minimum && fraction.endsWith('0')) fraction = fraction.slice(0, -1)
  if (options.grouping) whole = whole.replace(/\B(?=(\d{3})+(?!\d))/g, ',')
  const sign = rounded === 0n ? '' : parsed.negative ? '-' : options.signed ? '+' : ''
  return `${sign}${whole}${fraction ? `.${fraction}` : ''}`
}

function roundedMagnitude(parsed: ParsedDecimal, fractionDigits: number): bigint {
  const magnitude = BigInt(parsed.digits)
  if (parsed.scale <= fractionDigits) return magnitude * (10n ** BigInt(fractionDigits - parsed.scale))
  const divisor = 10n ** BigInt(parsed.scale - fractionDigits)
  const quotient = magnitude / divisor
  return magnitude % divisor * 2n >= divisor ? quotient + 1n : quotient
}

function multiplyByPowerOfTen(parsed: ParsedDecimal, power: number): ParsedDecimal {
  if (parsed.scale >= power) return { ...parsed, scale: parsed.scale - power }
  return { ...parsed, digits: `${parsed.digits}${'0'.repeat(power - parsed.scale)}`, scale: 0 }
}

function isZero(parsed: ParsedDecimal): boolean { return /^0+$/.test(parsed.digits) }
function isLessThanHundredth(parsed: ParsedDecimal): boolean {
  if (isZero(parsed) || parsed.scale <= 2) return false
  return BigInt(parsed.digits) < 10n ** BigInt(parsed.scale - 2)
}

export function formatMarketNumber(
  value: number | null | undefined,
  maximumFractionDigits = 8,
): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—'
  return value.toLocaleString('zh-CN', { maximumFractionDigits, useGrouping: true })
}

export function marketFrequencyLabel(frequency: MarketFrequency): string {
  return FREQUENCY_LABELS[frequency]
}

export function marketQuoteBasisLabel(frequency: MarketFrequency, dailyQuote: boolean): string {
  return dailyQuote ? '最近日线收盘' : `${marketFrequencyLabel(frequency)}收盘`
}

export function marketChangeBasisLabel(frequency: MarketFrequency, dailyQuote: boolean): string {
  return dailyQuote
    ? '日涨跌（较前一日收盘）'
    : `本周期涨跌（较前一根${marketFrequencyLabel(frequency)}收盘）`
}

export function quoteAvailabilityLabel(
  freshness: 'fresh' | 'stale' | 'unavailable',
  afterMarketFailed: boolean,
): string {
  const base = freshness === 'fresh' ? '报价可用' : freshness === 'stale' ? '报价过时' : '报价不可用'
  return afterMarketFailed && freshness !== 'unavailable' ? `${base} · 盘后更新异常` : base
}

export function formatMarketTime(
  value: string | null | undefined,
  frequency: MarketFrequency,
  tradingDay?: string | null,
): string {
  if (!value) return '—'
  if ((frequency === '1d' || frequency === '1w') && /^\d{4}-\d{2}-\d{2}$/.test(tradingDay ?? '')) {
    return `${tradingDay} · 交易日`
  }
  return formatBeijingInstant(value)
}

export function formatBeijingInstant(value: string | null | undefined): string {
  if (!value) return '—'
  const instant = new Date(value)
  if (!Number.isFinite(instant.getTime())) return '—'
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: SHANGHAI_TIME_ZONE,
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
  }).formatToParts(instant)
  const values = Object.fromEntries(parts.map((part) => [part.type, part.value]))
  return `${values.year}-${values.month}-${values.day} ${values.hour}:${values.minute} 北京时间`
}
