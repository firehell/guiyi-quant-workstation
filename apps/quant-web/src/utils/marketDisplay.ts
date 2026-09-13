import type { MarketFrequency } from '../types/market.ts'

const DECIMAL_TEXT = /^[+-]?(?:\d+(?:\.\d*)?|\.\d+)$/
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

/** Display-only Decimal normalization. It never converts the source string to Number. */
export function formatMarketDecimal(value: string | null | undefined): string {
  const raw = value?.trim()
  if (!raw || !DECIMAL_TEXT.test(raw)) return '—'
  const negative = raw.startsWith('-')
  const unsigned = raw.replace(/^[+-]/, '')
  const [wholeInput = '0', fractionInput = ''] = unsigned.split('.')
  const whole = wholeInput.replace(/^0+(?=\d)/, '') || '0'
  const fraction = fractionInput.replace(/0+$/, '')
  const zero = /^0+$/.test(whole) && fraction.length === 0
  return `${negative && !zero ? '-' : ''}${whole}${fraction ? `.${fraction}` : ''}`
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
