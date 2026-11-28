import request, { type ConditionalRequestConfig } from './request'
import type { AxiosResponse } from 'axios'

export type RunStatus = 'QUEUED' | 'RUNNING' | 'CANCELING' | 'SUCCEEDED' | 'FAILED' | 'CANCELED'
export type Amount = string | number
export type EvidenceFields = Record<string, unknown>

export interface RunConfig {
  strategy_id: string
  formula_version?: string
  profile_id?: string
  product: string
  contract: string
  signal_frequency: string
  warmup_start: string
  start: string
  end: string
  initial_capital: string
  commission_multiplier?: string
  slippage_ticks?: number
  parameters?: { execution_delay_minutes?: Amount }
  benchmark?: 'cash'
  sample_type?: 'historical' | 'experiment' | 'train' | 'oos'
}

export interface Metric {
  value: Amount | null
  definition?: string
  reason?: string | null
  unit?: string
  source?: string
}

export interface Summary extends EvidenceFields {
  metrics?: Record<string, Metric>
  source?: string
  sample_type?: string
  cost_basis?: string
  pairing_basis?: string
}

export interface IncrementalRun {
  source_run_id: string
  through: string
  appended_trading_days?: string[]
  executed_minutes?: number
}

export interface RunInterruption {
  status: 'ROLLOVER_INTERRUPTED'
  contract: string
  trading_day: string
  marked_at: string
  mark_price: string
  quantity: 1
  direction: 'LONG'
  entry_at: string
  entry_price: string
  unrealized_pnl: string
}

export interface Run {
  run_id: string
  status: RunStatus
  config: RunConfig & EvidenceFields
  created_at: string
  updated_at: string
  phase?: string
  diagnostic?: string | null
  source_run_id?: string | null
  can_extend?: boolean
  incremental?: IncrementalRun | null
  interruption?: RunInterruption | null
  qualification?: string | null
  summary?: Summary | null
  snapshot?: EvidenceFields | null
}

export interface RunFilters {
  strategy_id: string
  product: string
  signal_frequency: string
  start: string
  end: string
  status: string
  sort?: string
}

export interface RunPage {
  items: Run[]
  total: number
  counts: Partial<Record<RunStatus, number>>
  latest_attempt: Run | string | null
  latest_success: Run | string | null
}

export interface Eligibility {
  strategy_id: string
  label: string
  status: string
  reason: string
  formula_version?: string | null
  profile_id?: string | null
  product?: string | null
  signal_frequency?: string | null
  execution_frequency?: string | null
  links?: Record<string, string>
  research_parameters?: { execution_delay_minutes?: { min: number; max: number; default: number } }
}

export interface Template {
  template_id: string
  name: string
  config: RunConfig
}

export interface Rows<T> {
  items: T[]
  total: number
}

export interface RunRows<T> extends Rows<T> {
  run_id: string
}

export interface RunEvent {
  at: string
  status: RunStatus
  phase: string
  diagnostic?: string | null
}

export interface Trade extends EvidenceFields {
  trade_id: string
  contract: string
  direction: string
  quantity: Amount
  entry_at?: string | null
  exit_at?: string | null
  entry_price?: Amount | null
  exit_price?: Amount | null
  fees?: Amount | null
  net_pnl?: Amount | null
  unrealized_pnl?: Amount | null
  marked_at?: string | null
  valuation_at?: string | null
  mark_price?: Amount | null
  native_entry_id?: string | null
  native_exit_id?: string | null
  native_entry_ids?: string[]
  native_exit_ids?: string[]
  entry_signal_id?: string | null
  exit_signal_id?: string | null
  status: string
}

export interface Equity {
  at: string
  equity: Amount
  drawdown?: Amount | null
}

export interface ReplayBar {
  at: string
  open: Amount
  high: Amount
  low: Amount
  close: Amount
  in_position?: boolean
}

export interface ReplayMarker {
  at: string
  kind: string
  trade_id?: string
  signal_id?: string
  native_trade_id?: string
  quantity?: Amount | null
  price?: Amount | null
  label?: string | null
  event_at?: string
  position_end_at?: string
}

export interface NativeFill extends EvidenceFields {
  native_trade_id: string
  native_order_id?: string | null
  signal_id?: string | null
  contract?: string | null
  position_effect?: string | null
  quantity?: Amount | null
  price?: Amount | null
  fee?: Amount | null
}

export interface Replay {
  run_id: string
  available: boolean
  reason?: string | null
  contract?: string
  frequency?: string
  revision?: string
  input_sha256?: string | null
  bars?: ReplayBar[]
  markers?: ReplayMarker[]
  trade?: Trade
  native_fills?: NativeFill[]
  attempts?: EvidenceFields[]
}

export type ExperimentKind = 'comparison' | 'oos' | 'walk_forward'
export type ExperimentAxis = 'parameters' | 'strategy' | 'product' | 'frequency' | 'commission' | 'slippage'
export type SelectionMetric = 'net_return' | 'max_drawdown'
export interface FoldConfig {
  train_warmup_start: string
  train_start: string
  train_end: string
  test_warmup_start: string
  test_start: string
  test_end: string
}

export interface ExperimentConfig {
  request_key: string
  kind: ExperimentKind
  axes: ExperimentAxis[]
  configs: RunConfig[]
  metric: SelectionMetric
  folds?: FoldConfig[]
}

export interface ExperimentMember {
  member_id: string
  fold?: number | null
  phase: string
  research_config: RunConfig
  run_id?: string | null
  status: string
  diagnostic?: string | null
  metrics?: Record<string, Metric | Amount | null>
}

export interface ExperimentFold extends EvidenceFields {
  fold: number
  selection_cutoff?: string
  selected_member_id?: string | null
  test_member_id?: string | null
  status: string
  diagnostic?: string | null
}

export interface Experiment {
  experiment_id: string
  kind: ExperimentKind
  status: string
  created_at: string
  updated_at: string
  definition?: EvidenceFields
  members?: ExperimentMember[]
  folds?: ExperimentFold[]
  comparison?: EvidenceFields
  evidence?: EvidenceFields
}

const root = '/backtests'
const runPath = (id: string) => `${root}/runs/${encodeURIComponent(id)}`
const experimentPath = (id: string) => `${root}/experiments/${encodeURIComponent(id)}`
const activePhases = new Set(['QUEUED', 'RUNNING', 'CANCELING'])

export function runInProgress(status?: string) {
  return status !== undefined && activePhases.has(status)
}

export function diagnosticCode(error: unknown): string | undefined {
  const response = (error as { response?: { status?: number; data?: { detail?: { code?: unknown } } } })?.response
  const value = response?.data?.detail?.code
  if (typeof value === 'string' && /^[A-Z0-9_]{1,96}$/.test(value)) return value
  return response?.status === 422 ? 'INPUT_VALIDATION_FAILED' : undefined
}

export const readEligibility = (signal: AbortSignal) =>
  request.get<unknown, { items: Eligibility[] }>(`${root}/eligibility`, { signal })

export const readTemplates = (signal: AbortSignal) =>
  request.get<unknown, { items: Template[] }>(`${root}/templates`, { signal })

export const saveTemplate = (id: string, name: string, config: RunConfig) =>
  request.put<unknown, Template>(`${root}/templates/${encodeURIComponent(id)}`, { name, config })

export const readRuns = (filters: RunFilters, offset: number, limit: number, signal: AbortSignal) =>
  request.get<unknown, RunPage>(`${root}/runs`, {
    params: { ...Object.fromEntries(Object.entries(filters).filter(([, value]) => value)), offset, limit }, signal,
  })

async function acceptRun(path: string, body: { request_key: string; config?: RunConfig; end?: string }) {
  const response = await request.post<unknown, AxiosResponse<Run>>(path, body, { preserveResponse: true } as ConditionalRequestConfig)
  const id = response.data?.run_id
  if (response.status !== 202 || typeof id !== 'string' || !/^[A-Za-z0-9_-]{1,100}$/.test(id)) {
    throw new Error('BACKTEST_SUBMISSION_UNCONFIRMED')
  }
  return response.data
}

export const submitRun = (request_key: string, config: RunConfig) =>
  acceptRun(`${root}/runs`, { request_key, config })

export const readRun = (id: string, signal: AbortSignal) =>
  request.get<unknown, Run>(runPath(id), { signal })

export const cancelRun = (id: string) => request.post<unknown, Run>(`${runPath(id)}/cancel`)

export const rerun = (id: string, request_key: string) =>
  acceptRun(`${runPath(id)}/rerun`, { request_key })

export const extendRun = (id: string, end: string, request_key: string) =>
  acceptRun(`${runPath(id)}/extend`, { end, request_key })

export const readRunEvents = (id: string, signal: AbortSignal) =>
  request.get<unknown, { run_id: string; items: RunEvent[] }>(`${runPath(id)}/events`, { signal })

export const readTrades = (id: string, offset: number, limit: number, signal: AbortSignal) =>
  request.get<unknown, RunRows<Trade>>(`${runPath(id)}/trades`, { signal, params: { offset, limit } })

export const readEquity = (id: string, offset: number, limit: number, signal: AbortSignal) =>
  request.get<unknown, RunRows<Equity>>(`${runPath(id)}/equity`, { signal, params: { offset, limit } })

export const readReplay = (id: string, trade: string, signal: AbortSignal) =>
  request.get<unknown, Replay>(`${runPath(id)}/replay/${encodeURIComponent(trade)}`, { signal })

export const readReport = (id: string, signal: AbortSignal) =>
  request.get<unknown, EvidenceFields>(`${runPath(id)}/report`, { signal })

export const readExperiments = (signal: AbortSignal) =>
  request.get<unknown, Rows<Experiment>>(`${root}/experiments`, { signal })

export async function submitExperiment(definition: ExperimentConfig) {
  const response = await request.post<unknown, AxiosResponse<Experiment>>(
    `${root}/experiments`, definition, { preserveResponse: true } as ConditionalRequestConfig,
  )
  const id = response.data?.experiment_id
  if (response.status !== 202 || typeof id !== 'string' || !/^[a-f0-9]{32}$/.test(id)) {
    throw new Error('BACKTEST_SUBMISSION_UNCONFIRMED')
  }
  return response.data
}

export const readExperiment = (id: string, signal: AbortSignal) =>
  request.get<unknown, Experiment>(experimentPath(id), { signal })

export const readExperimentEvidence = (id: string, signal: AbortSignal) =>
  request.get<unknown, EvidenceFields>(`${experimentPath(id)}/evidence`, { signal })
