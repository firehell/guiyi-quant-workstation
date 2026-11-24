export const backtestFrequencies = ['5m', '15m', '30m', '60m', '1d', '1w'] as const
export type BacktestKind = 'trades' | 'equity'

export interface BacktestSelection {
  product: string
  strategy: string
  frequency: string
  research_profile_id: string
}

export function backtestSelection(product: string, strategy: string, frequency: string, trial: boolean): BacktestSelection | null {
  if (!['trend', 'oscillation', 'dual_fusion'].includes(strategy)
    || !backtestFrequencies.some(value => value === frequency)) return null
  return { product: product.toLowerCase(), strategy, frequency,
    research_profile_id: `${strategy}_${frequency}_rqalpha${trial ? '_trial' : ''}_v1` }
}

export interface LatestBacktest {
  result: {
    run_id: string
    as_of_trading_day: string
    qualification: 'QUALIFIED' | 'TRIAL'
    manifest: Record<string, unknown>
    summary: Record<string, unknown>
  } | null
  last_attempt: {
    run_id: string
    generation: number
    status: 'RUNNING' | 'SUCCEEDED' | 'FAILED'
    error_code: string | null
    as_of_trading_day: string
  } | null
}

export type BacktestRow = Record<string, unknown> & { seq: number }
interface Page { run_id: string; items: BacktestRow[]; next_cursor: string | null }
interface PageState { items: BacktestRow[]; cursor: string | null; loaded: boolean; loading: boolean; error: boolean }
interface ReaderState { latest: LatestBacktest | null; loading: boolean; error: boolean; trades: PageState; equity: PageState }
interface BacktestAPI {
  latest(key: BacktestSelection, signal: AbortSignal): Promise<LatestBacktest>
  page(runId: string, kind: BacktestKind, cursor: string | null, signal: AbortSignal): Promise<Page>
}

const emptyPage = (): PageState => ({ items: [], cursor: null, loaded: false, loading: false, error: false })

export function createBacktestReader(api: BacktestAPI, changed: (state: ReaderState) => void) {
  let controller = new AbortController()
  const state: ReaderState = { latest: null, loading: false, error: false, trades: emptyPage(), equity: emptyPage() }
  const notify = () => changed({ ...state, trades: { ...state.trades }, equity: { ...state.equity } })

  async function more(kind: BacktestKind) {
    const signal = controller.signal
    const runId = state.latest?.result?.run_id
    const page = state[kind]
    if (!runId || page.loading || (page.loaded && !page.cursor)) return
    page.loading = true
    page.error = false
    notify()
    try {
      const response = await api.page(runId, kind, page.cursor, signal)
      if (signal.aborted) return
      if (response.run_id !== runId || (response.next_cursor && response.next_cursor === page.cursor)) {
        throw new Error('BACKTEST_PAGE_MISMATCH')
      }
      page.items = [...page.items, ...response.items]
      page.cursor = response.next_cursor
      page.loaded = true
    } catch {
      if (!signal.aborted) page.error = true
    } finally {
      if (!signal.aborted) {
        page.loading = false
        notify()
      }
    }
  }

  async function select(key: BacktestSelection | null) {
    controller.abort()
    controller = new AbortController()
    const signal = controller.signal
    Object.assign(state, { latest: null, loading: key !== null, error: false, trades: emptyPage(), equity: emptyPage() })
    notify()
    if (!key) return
    try {
      const latest = await api.latest(key, signal)
      if (signal.aborted) return
      state.latest = latest
      state.loading = false
      notify()
      await Promise.all([more('trades'), more('equity')])
    } catch {
      if (!signal.aborted) {
        state.loading = false
        state.error = true
        notify()
      }
    }
  }

  return { state, select, more, dispose: () => controller.abort() }
}
