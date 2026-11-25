import type { BarData, KlineMarker } from '@/types/market'

export const newowAfterMarketOnly = import.meta.env?.VITE_NEWOW_EOD_ISOLATED === '1'

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
    finished_at?: string
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
  let seriesId: string | null = null
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
    const nextId = key ? JSON.stringify(key) : null
    const retain = nextId !== null && nextId === seriesId
    seriesId = nextId
    if (!retain) Object.assign(state, { latest: null, trades: emptyPage(), equity: emptyPage() })
    Object.assign(state, { loading: key !== null, error: false })
    notify()
    if (!key) return
    try {
      const latest = await api.latest(key, signal)
      if (signal.aborted) return
      if (state.latest?.result?.run_id !== latest.result?.run_id) {
        state.trades = emptyPage()
        state.equity = emptyPage()
      } else {
        state.trades.loading = false
        state.equity.loading = false
      }
      state.latest = latest
      state.loading = false
      notify()
      if (latest.result?.summary.result_kind !== 'reference_only') {
        await Promise.all([!state.trades.loaded && more('trades'), !state.equity.loaded && more('equity')])
      }
    } catch {
      if (!signal.aborted) {
        state.loading = false
        state.trades.loading = false
        state.equity.loading = false
        state.error = true
        notify()
      }
    }
  }

  return { state, select, more, dispose: () => controller.abort() }
}


export function publishedActionMarkers(
  result: LatestBacktest['result'], bars: readonly BarData[], frequency: string,
): KlineMarker[] {
  if (!result) return []
  const actions = result.summary.decisions
  const contract = result.manifest.physical_contract
  if (!Array.isArray(actions) || typeof contract !== 'string') return []
  const byTime = new Map(bars.map(bar => [Date.parse(bar.time), bar]))
  return actions.flatMap(action => {
    if (!action || typeof action.decision_id !== 'string' || typeof action.signal_bar_end !== 'string'
      || (action.action !== 'BUILD' && action.action !== 'CLEAR') || action.frequency !== frequency) return []
    const frozen = action.bar
    const active = byTime.get(Date.parse(action.signal_bar_end))
    if (!active || active.confirmed === false || active.physicalContract?.toUpperCase() !== contract.toUpperCase()
      || !frozen || frozen.completed !== true || frozen.frequency !== frequency
      || frozen.physical_contract !== contract || active.trading_day !== frozen.trading_day
      || Date.parse(frozen.bar_end) !== Date.parse(active.time)
      || !(['open', 'high', 'low', 'close', 'volume'] as const).every(field => frozen[field] != null && Number(frozen[field]) === active[field])) return []
    const build = action.action === 'BUILD'
    return [{
      id: action.decision_id, time: action.signal_bar_end,
      label: (result.qualification === 'TRIAL' ? '牛哇试验参考' : '牛哇盘后参考') + (build ? '建仓' : '清仓'),
      tooltip: typeof action.reason === 'string' ? action.reason : undefined,
      position: build ? 'belowBar' : 'aboveBar', shape: build ? 'arrowUp' : 'arrowDown',
      tone: result.qualification === 'TRIAL' ? 'neutral' : build ? 'up' : 'down',
    }]
  })
}
