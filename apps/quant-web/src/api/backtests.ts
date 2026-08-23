import axios, { type AxiosAdapter, type AxiosInstance } from 'axios'
import { BACKTEST_ARTIFACT_KINDS } from '../types/backtest.ts'

import type {
  ArtifactKind,
  BacktestHealth,
  BacktestHttpErrorCode,
  BacktestRunDetail,
  BacktestRunForm,
  BacktestNormalizedRunRequest,
  BacktestRunSummary,
  BacktestSafeError,
  BacktestStrategy,
} from '../types/backtest.ts'


export const DEFAULT_BACKTEST_API_BASE_URL = 'http://127.0.0.1:8011/api/v1/backtests'
const BACKTEST_BASE_URL_PATTERN = /^http:\/\/(?:localhost|127\.0\.0\.1):8011\/api\/v1\/backtests$/

const SAFE_ERROR_MESSAGES: Record<BacktestHttpErrorCode, string> = {
  BACKTEST_LOCAL_UNAVAILABLE: '本机回测服务不可用，请检查本机配置并重试。',
  RUNNER_UNAVAILABLE: 'RQAlpha 运行环境不可用，请检查本机配置。',
  BUNDLE_UNAVAILABLE: '本地 Bundle 不可用，请检查只读数据路径。',
  REGISTRY_INVALID: '回测策略注册表不可用。',
  STRATEGY_NOT_FOUND: '未找到可用的注册策略。',
  INVALID_BACKTEST_REQUEST: '回测配置无效，请检查表单。',
  BACKTEST_ALREADY_RUNNING: '已有回测正在运行，请等待完成后再试。',
  BACKTEST_RUN_NOT_FOUND: '未找到该回测记录。',
  BACKTEST_ARTIFACT_NOT_FOUND: '该回测产物不可用。',
}

const ERROR_CODES = new Set<BacktestHttpErrorCode>(
  Object.keys(SAFE_ERROR_MESSAGES) as BacktestHttpErrorCode[],
)
const ARTIFACT_KINDS: ReadonlySet<string> = new Set(BACKTEST_ARTIFACT_KINDS)

export interface BacktestClient {
  health(): Promise<BacktestHealth>
  listStrategies(): Promise<BacktestStrategy[]>
  startRun(form: BacktestRunForm): Promise<BacktestRunSummary>
  listRuns(limit?: number): Promise<BacktestRunSummary[]>
  getRun(runId: string): Promise<BacktestRunDetail>
  artifactUrl(runId: string, kind: ArtifactKind): string
}

export interface BacktestClientOptions {
  baseURL?: string
  adapter?: AxiosAdapter
  hostname?: string
}

export class BacktestClientError extends Error {
  readonly code: BacktestHttpErrorCode

  constructor(code: BacktestHttpErrorCode) {
    super(code)
    this.name = 'BacktestClientError'
    this.code = code
  }
}

export function resolveBacktestApiBaseUrl(configured?: string) {
  const value = configured?.trim() ?? ''
  if (!value) return DEFAULT_BACKTEST_API_BASE_URL
  if (!BACKTEST_BASE_URL_PATTERN.test(value)) {
    throw new BacktestClientError('BACKTEST_LOCAL_UNAVAILABLE')
  }
  return value
}

export function isLocalBacktestHostname(hostname: string) {
  const normalized = hostname.toLowerCase()
  return normalized === 'localhost' || normalized === '127.0.0.1'
}

export function serializeBacktestRunRequest(form: BacktestRunForm): BacktestNormalizedRunRequest {
  return {
    strategy_id: form.strategyId,
    start_date: form.startDate,
    end_date: form.endDate,
    frequency: form.frequency,
    future_cash: form.futureCash,
    matching_type: form.matchingType,
    margin_multiplier: form.marginMultiplier,
    futures_commission_multiplier: form.futuresCommissionMultiplier,
    slippage_model: form.slippageModel,
    slippage: form.slippage,
    parameters: { ...form.parameters },
  }
}

export function artifactUrl(baseURL: string, runId: string, kind: ArtifactKind) {
  const base = resolveBacktestApiBaseUrl(baseURL)
  if (!ARTIFACT_KINDS.has(kind)) {
    throw new BacktestClientError('BACKTEST_ARTIFACT_NOT_FOUND')
  }
  return `${base}/runs/${encodeURIComponent(runId)}/artifacts/${kind}`
}

export function mapBacktestError(error: unknown): BacktestSafeError {
  const code = readSafeErrorCode(error) ?? 'BACKTEST_LOCAL_UNAVAILABLE'
  return { code, message: SAFE_ERROR_MESSAGES[code] }
}

export function createBacktestClient(options: BacktestClientOptions = {}): BacktestClient {
  const configured = options.baseURL ?? import.meta.env?.VITE_BACKTEST_API_BASE_URL
  const baseURL = resolveBacktestApiBaseUrl(configured)
  const hostname = options.hostname ?? browserHostname()
  const instance: AxiosInstance = axios.create({
    baseURL,
    timeout: 30_000,
    headers: { 'Content-Type': 'application/json' },
    adapter: options.adapter,
  })

  function requireLocalBrowser() {
    if (hostname !== undefined && !isLocalBacktestHostname(hostname)) {
      return Promise.reject(new BacktestClientError('BACKTEST_LOCAL_UNAVAILABLE'))
    }
    return undefined
  }

  function get<T>(path: string, config?: { params: Record<string, number> }) {
    return requireLocalBrowser() ?? instance.get<T>(path, config).then((response) => response.data)
  }

  return {
    health: () => get<BacktestHealth>('/health'),
    listStrategies: () => get<BacktestStrategy[]>('/strategies'),
    startRun: (form) => requireLocalBrowser()
      ?? instance.post<BacktestRunSummary>('/runs', serializeBacktestRunRequest(form))
        .then((response) => response.data),
    listRuns: (limit = 20) => get<BacktestRunSummary[]>('/runs', { params: { limit } }),
    getRun: (runId) => get<BacktestRunDetail>(`/runs/${encodeURIComponent(runId)}`),
    artifactUrl: (runId, kind) => artifactUrl(baseURL, runId, kind),
  }
}

function browserHostname() {
  if (typeof window === 'undefined') return undefined
  return window.location.hostname
}

function readSafeErrorCode(error: unknown): BacktestHttpErrorCode | undefined {
  if (!isRecord(error)) return undefined
  if (typeof error.code === 'string' && ERROR_CODES.has(error.code as BacktestHttpErrorCode)) {
    return error.code as BacktestHttpErrorCode
  }
  const response = error.response
  if (!isRecord(response)) return undefined
  const data = response.data
  if (!isRecord(data)) return undefined
  const detail = data.detail
  if (!isRecord(detail)) return undefined
  const code = detail.code
  if (typeof code !== 'string' || !ERROR_CODES.has(code as BacktestHttpErrorCode)) {
    return undefined
  }
  return code as BacktestHttpErrorCode
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}

export const backtestClient = createBacktestClient()
