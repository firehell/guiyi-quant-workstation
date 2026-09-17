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

export function marketHomeQualityNotice(reasons: readonly string[]): string | null {
  const notices: string[] = []
  if (reasons.includes('daily_history_unavailable')) notices.push('日线历史不完整；日线指标不可用')
  else if (reasons.includes('daily_price_interrupted')) notices.push(reasons.includes('daily_rewarming')
    ? '历史日线有缺价；日趋势重新预热中'
    : '历史日线有缺价；日线指标仅使用缺价后的连续数据')
  if (reasons.includes('weekly_history_unavailable')) notices.push('周线历史不完整；周趋势不可用')
  if (reasons.includes('weekly_price_unavailable')) notices.push('周线价格不可用；周趋势不可用')
  return notices.length ? notices.join('。') : null
}
