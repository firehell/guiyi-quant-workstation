export type ResearchSummary = Record<string, unknown> & { status: string }

export function metricText(summary: ResearchSummary | null, key: string, suffix = ''): string {
  if (!summary || summary.status !== 'COMPLETED') return '不可评价'
  const value = summary[key]
  return typeof value === 'string' || typeof value === 'number' ? `${value}${suffix}` : '未提供'
}

export function runStateText(status: string): string {
  return ({ COMPLETED: '历史回放完成', SEGMENTED: '合约段分离，年度不可评价', ROLLOVER_INTERRUPTED: '换月中断', DATA_INSUFFICIENT: '数据不足', EXECUTION_FACTS_MISSING: '执行事实缺失', INTERRUPTED: '合约段中断' } as Record<string, string>)[status] ?? `未验证：${status}`
}

export function decisionMatches(item: Record<string, unknown>, action: string, search: string): boolean {
  if (action !== 'ALL' && item.action !== action) return false
  if (!search.trim()) return true
  const haystack = [item.action, item.side, item.reason, JSON.stringify(item.facts ?? {})].join(' ').toLowerCase()
  return haystack.includes(search.trim().toLowerCase())
}

export function selectionToken(runId: string, generation: number): string {
  return `${generation}:${runId}`
}

export function equityPoints(items: Array<Record<string, unknown>>): string {
  const values = items.map(item => Number(item.equity))
  if (values.length < 2 || values.some(value => !Number.isFinite(value))) return ''
  const min = Math.min(...values)
  const max = Math.max(...values)
  const span = max - min || 1
  return values.map((value, index) => `${(index / (values.length - 1) * 100).toFixed(2)},${(100 - (value - min) / span * 100).toFixed(2)}`).join(' ')
}
