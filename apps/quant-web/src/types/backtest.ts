export type BacktestFrequency = '1d' | '1m'
export type BacktestMatchingType = 'current_bar' | 'next_bar'
export type BacktestSlippageModel = 'PriceRatioSlippage' | 'TickSizeSlippage'
export type BacktestParameterType = 'integer' | 'decimal' | 'boolean' | 'enum'
export type BacktestParameterValue = number | string | boolean
export type RunStatus = 'running' | 'succeeded' | 'failed' | 'timed_out' | 'interrupted'
export type ArtifactKind =
  | 'report_zip'
  | 'result_pickle'
  | 'equity_png'
  | 'stdout_log'
  | 'stderr_log'
  | 'run_json'

export type BacktestHttpErrorCode =
  | 'BACKTEST_LOCAL_UNAVAILABLE'
  | 'RUNNER_UNAVAILABLE'
  | 'BUNDLE_UNAVAILABLE'
  | 'REGISTRY_INVALID'
  | 'STRATEGY_NOT_FOUND'
  | 'INVALID_BACKTEST_REQUEST'
  | 'BACKTEST_ALREADY_RUNNING'
  | 'BACKTEST_RUN_NOT_FOUND'
  | 'BACKTEST_ARTIFACT_NOT_FOUND'

export interface BacktestSafeError {
  code: BacktestHttpErrorCode
  message: string
}

export interface BacktestRunForm {
  strategyId: string
  startDate: string
  endDate: string
  frequency: BacktestFrequency
  futureCash: string
  matchingType: BacktestMatchingType
  marginMultiplier: string
  futuresCommissionMultiplier: string
  slippageModel: BacktestSlippageModel
  slippage: string
  parameters: Record<string, unknown>
}

export interface BacktestRunRequest {
  strategy_id: string
  start_date: string
  end_date: string
  frequency: BacktestFrequency
  future_cash: string
  matching_type: BacktestMatchingType
  margin_multiplier: string
  futures_commission_multiplier: string
  slippage_model: BacktestSlippageModel
  slippage: string
  parameters: Record<string, unknown>
}

export interface BacktestParameterDescriptor {
  name: string
  type: BacktestParameterType
  default: BacktestParameterValue
  minimum: number | string | null
  maximum: number | string | null
  options: string[]
}

export interface BacktestStrategy {
  id: string
  name: string
  description: string
  supported_frequencies: BacktestFrequency[]
  defaults: Record<string, string>
  parameters: BacktestParameterDescriptor[]
  research_only: true
  formal_evidence: false
  promotion_eligible: false
}

export interface BacktestRunnerHealth {
  available: boolean
  rqalpha_version: string | null
  rqsdk_version: string | null
  python_version: string | null
}

export interface BacktestHealth {
  status: 'ready' | 'degraded'
  research_only: true
  formal_evidence: false
  promotion_eligible: false
  busy: boolean
  runner: BacktestRunnerHealth
  bundle_available: boolean
  runs_root_available: boolean
  registry_available: boolean
  error: { code: BacktestHttpErrorCode } | null
}

export interface BacktestVersions {
  rqalpha: string | null
  rqsdk: string | null
  python: string | null
}

export interface BacktestRunSummary {
  run_id: string
  research_only: true
  formal_evidence: false
  promotion_eligible: false
  strategy_id: string
  strategy_name: string
  strategy_entry_file: string
  strategy_sha256: string
  repository_commit: string
  bundle_path: string
  versions: BacktestVersions
  requested_config: BacktestRunRequest
  effective_config: Record<string, unknown>
  effective_parameters: Record<string, BacktestParameterValue>
  status: RunStatus
  started_at: string
  finished_at: string | null
  exit_code: number | null
  failure_code: string | null
}

export interface BacktestSummary {
  total_returns: string
  annualized_returns: string
  max_drawdown: string
  sharpe: string
  sortino: string
  volatility: string
  total_value: string
  cash: string
}

export interface BacktestEquityPoint {
  date: string
  unit_net_value: string
}

export type BacktestArtifactAvailability = Record<ArtifactKind, boolean>

export interface BacktestResult {
  summary: BacktestSummary
  equity: BacktestEquityPoint[]
  trade_count: string
  artifacts: BacktestArtifactAvailability
}

export interface BacktestRunDetail extends BacktestRunSummary {
  result: BacktestResult | null
  stdout_tail: string
  stderr_tail: string
}

export interface BacktestCapability {
  kind: 'ready' | 'local_unavailable' | 'remote_blocked'
  showMenu: boolean
  canStart: boolean
  health: BacktestHealth | null
  error: BacktestSafeError | null
}

export type BacktestFormErrors = Record<string, string>
