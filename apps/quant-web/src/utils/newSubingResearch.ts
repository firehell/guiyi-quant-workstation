export type ResearchSummary = Record<string, unknown> & { status: string }

const DECIMAL_TEXT = /^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$/
const ZERO_TEXT = /^[+-]?0*(?:\.0*)?(?:[eE][+-]?\d+)?$/

export function metricText(summary: ResearchSummary | null, key: string, suffix = ''): string {
  if (!summary || summary.status !== 'COMPLETED') return '不可评价'
  const value = summary[key]
  if (typeof value !== 'string' && typeof value !== 'number') return '未提供'
  const original = String(value)
  const digits = key === 'account_return_pct' || key === 'max_drawdown_pct' ? 3
    : key === 'final_equity' || key === 'initial_cash' || key === 'total_fees' ? 2 : null
  if (digits === null || !DECIMAL_TEXT.test(original)) return `${original}${suffix}`
  const numeric = Number(original)
  const safe = Number.isFinite(numeric) && Math.abs(numeric) <= Number.MAX_SAFE_INTEGER / (10 ** digits)
    && (numeric !== 0 || ZERO_TEXT.test(original))
  if (!safe) return `${original}${suffix}`
  return `${new Intl.NumberFormat('en-US', { useGrouping: false, minimumFractionDigits: digits, maximumFractionDigits: digits }).format(numeric)}${suffix}`
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
