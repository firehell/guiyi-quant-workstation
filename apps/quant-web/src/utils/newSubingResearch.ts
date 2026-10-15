export type ResearchSummary = Record<string, unknown> & { status: string }

type RunSelection = { product: string; scenario: string; strategy_code: string; initial_cash?: string }
type ProfileSelection = { product: string; strategy_code?: string; initial_cash: string }

export function matchingRun(run: RunSelection, strategy: string, cash: string, product: string, scenario: string): boolean {
  return run.strategy_code === strategy && run.product === product && run.scenario === scenario
    && (strategy === 'new_subing_v1' ? cash === '100000' && (run.initial_cash === undefined || run.initial_cash === '100000') : run.initial_cash === cash)
}

export function matchingProfile(profile: ProfileSelection, strategy: string, cash: string, product: string): boolean {
  return (profile.strategy_code ?? 'new_subing_v1') === strategy && profile.initial_cash === cash && profile.product === product
}

const DECIMAL_TEXT = /^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$/
const ZERO_TEXT = /^[+-]?0*(?:\.0*)?(?:[eE][+-]?\d+)?$/

export function metricText(summary: ResearchSummary | null, key: string, suffix = ''): string {
  if (!summary || summary.status !== 'COMPLETED') return '不可评价'
  const value = summary[key]
  if (typeof value !== 'string' && typeof value !== 'number') return '未提供'
  const original = String(value)
  const digits = key === 'account_return_pct' || key === 'max_drawdown_pct' ? 2
    : key === 'final_equity' || key === 'initial_cash' || key === 'total_fees' ? 2 : null
  if (digits === null || !DECIMAL_TEXT.test(original)) return `${original}${suffix}`
  const numeric = Number(original)
  const safe = Number.isFinite(numeric) && Math.abs(numeric) <= Number.MAX_SAFE_INTEGER / (10 ** digits)
    && (numeric !== 0 || ZERO_TEXT.test(original))
  if (!safe) return `${original}${suffix}`
  if (numeric !== 0 && Math.abs(numeric) < 10 ** -digits) return `${numeric < 0 ? '-' : ''}<${(10 ** -digits).toFixed(digits)}${suffix}`
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

export function researchCurvePoints(items: Array<Record<string, unknown>>) {
  return items.map((item, index) => ({
    value: item.equity === null || item.equity === undefined ? null : Number(item.equity),
    date: String(item.at ?? '').slice(0, 10),
    position: Date.parse(String(item.at ?? '')),
    segment: JSON.stringify([item.physical_contract, item.segment_id, item.status, item.interrupted]),
    at: String(item.at ?? ''), index,
  }))
}

export function appendResearchPage<T extends { items: Array<Record<string, unknown>>; run_id: string; sha256: string }>(previous: T, next: T): T {
  if (previous.run_id !== next.run_id || previous.sha256 !== next.sha256) throw new Error('研究结果身份不一致')
  return { ...next, items: [...previous.items, ...next.items] }
}

export function normalizeResearchVisit(raw: unknown) {
  const saved = raw && typeof raw === 'object' ? raw as Record<string, unknown> : {}
  const version: 'new_subing_v1' | 'new_subing_v2' = saved.version === 'new_subing_v1' ? 'new_subing_v1' : 'new_subing_v2'
  return {
    version,
    capital: version === 'new_subing_v2' && saved.capital === '1000000' ? '1000000' : '100000',
    product: (['AL', 'RB', 'TA'] as const).find(value => value === saved.product) ?? 'AL',
    scenario: (['baseline', 'double_commission', 'double_slippage'] as const).find(value => value === saved.scenario) ?? 'baseline',
    kind: (['decisions', 'trades', 'equity'] as const).find(value => value === saved.kind) ?? 'decisions',
    action: typeof saved.action === 'string' ? saved.action : 'ALL',
    query: typeof saved.query === 'string' ? saved.query : '',
    scroll: typeof saved.scroll === 'number' && Number.isFinite(saved.scroll) ? Math.max(0, saved.scroll) : 0,
  }
}
