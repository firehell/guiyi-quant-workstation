const priceFormat = new Intl.NumberFormat('zh-CN', { maximumSignificantDigits: 21 })

export function marketHomePercent(value: number | null): string {
  if (value === null || !Number.isFinite(value)) return '—'
  if (value === 0) return '0.00%'
  return `${value > 0 ? '+' : ''}${(value * 100).toFixed(2)}%`
}

export function marketHomePrice(value: number | null): string {
  return value === null || !Number.isFinite(value) ? '—' : priceFormat.format(value)
}

export function marketHomeDirection(value: number | null): 'up' | 'down' | 'flat' {
  return value === null || !Number.isFinite(value) || value === 0 ? 'flat' : value > 0 ? 'up' : 'down'
}

export function marketHomeRatio(value: number | null): string {
  return value === null || !Number.isFinite(value) ? '—' : value.toFixed(2)
}
