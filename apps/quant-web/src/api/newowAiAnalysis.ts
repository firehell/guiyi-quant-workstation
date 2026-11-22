import { previewInstant } from '../utils/candidatePreviewInstant.ts'

export interface AiSummary {
  cumulative_return: string
  win_rate: number
  max_drawdown: string
  trade_count: number
  terminal_valuation_count: number
  segment_count: number
  warming_segment_count: number
}
export interface AiCombo {
  strategy: 'oscillation' | 'trend'
  frequency: '1w' | '1d' | '60m'
  since: string
  through: string | null
  source_bars: number
  input_sha256: string | null
  summary: AiSummary | null
  reason_code: string | null
  score: string | null
  confidence: 'high' | 'mid' | null
  is_best: boolean
}
export interface AiFourStepSummary {
  trade_count: number
  win_rate: number
  average_return_pct: string
  worst_return_pct: string
  average_holding_bars: number
  trend_leg_count: number
  trend_exit_count: number
  terminal_valuation_count: number
}
export interface AiFourStep {
  since: string
  through: string | null
  source_bars: number
  input_sha256: string | null
  model_version: 'newow_dual_four_step_page_v1' | 'newow_dual_four_step_gap_fill_page_v1'
  futures_adapter_version: 'guiyi_newow_four_step_segment_valuation_v1'
  page_source_sha256: string
  summary: AiFourStepSummary | null
  page_baseline: AiFourStepSummary | null
  reason_code: string | null
}
export interface AiAnalysis {
  schema_version: 'newow_ai_analysis_v2' | 'newow_ai_analysis_v3' | 'newow_ai_analysis_v4'
  product: string
  as_of: string
  formula_version: 'newow_ai_summary_ranking_page_v1'
  futures_adapter_version: 'guiyi_newow_ai_segment_valuation_v1'
  page_source_sha256: string
  page_kernel_parity: true
  page_parity: false
  executable: false
  combos: AiCombo[]
  four_step?: AiFourStep | null
}
type Transport = (path: string, config: { params: { product: string; as_of: string }; signal?: AbortSignal; timeout: number }) => Promise<unknown>
const record = (v: unknown): v is Record<string, unknown> => typeof v === 'object' && v !== null && !Array.isArray(v)
const integer = (v: unknown): v is number => Number.isSafeInteger(v) && Number(v) >= 0
const decimal = (v: unknown): v is string => typeof v === 'string' && /^-?\d+(?:\.\d+)?$/.test(v) && Number.isFinite(Number(v))
const digest = (v: unknown) => typeof v === 'string' && /^[a-f0-9]{64}$/.test(v)
const day = (v: unknown): v is string => typeof v === 'string' && /^\d{4}-\d\d-\d\d$/.test(v) && Number.isFinite(Date.parse(v)) && new Date(v).toISOString().slice(0, 10) === v

function fourStepSummary(value: unknown): value is AiFourStepSummary {
  if (!record(value) || !integer(value.trade_count) || value.trade_count === 0
    || !integer(value.win_rate) || value.win_rate > 100 || !decimal(value.average_return_pct)
    || !decimal(value.worst_return_pct) || !integer(value.average_holding_bars)) return false
  for (const count of [value.trend_leg_count, value.trend_exit_count, value.terminal_valuation_count]) {
    if (!integer(count) || count > value.trade_count) return false
  }
  return true
}
function validFourStep(value: unknown, daily: unknown, gapFill: boolean): boolean {
  if (value == null) return !gapFill
  if (!record(value) || !record(daily) || value.since !== daily.since || value.through !== daily.through
    || value.source_bars !== daily.source_bars || value.input_sha256 !== daily.input_sha256
    || value.model_version !== (gapFill ? 'newow_dual_four_step_gap_fill_page_v1' : 'newow_dual_four_step_page_v1')
    || value.futures_adapter_version !== 'guiyi_newow_four_step_segment_valuation_v1'
    || !digest(value.page_source_sha256)
    || (gapFill && value.page_source_sha256 !== '16ff7e4284f5bea252da84d6ad7ae2f29ba1fcf443c126cd85a46fa36af91796')) return false
  if (value.summary === null) return value.page_baseline === null && typeof value.reason_code === 'string'
  return fourStepSummary(value.summary) && fourStepSummary(value.page_baseline) && value.reason_code === null
    && value.summary.trade_count === value.page_baseline.trade_count && Number(value.source_bars) >= 60
}

export function validateAiAnalysis(value: unknown, product: string, asOf: string): value is AiAnalysis {
  if (!record(value) || !['newow_ai_analysis_v2', 'newow_ai_analysis_v3', 'newow_ai_analysis_v4'].includes(String(value.schema_version)) || value.product !== product
    || typeof value.as_of !== 'string' || previewInstant(asOf) === null || previewInstant(value.as_of) !== previewInstant(asOf)
    || value.formula_version !== 'newow_ai_summary_ranking_page_v1'
    || value.futures_adapter_version !== 'guiyi_newow_ai_segment_valuation_v1'
    || value.page_source_sha256 !== 'b12da74d89a7ac304d7479999d11f13ab53ced834a8472f937d78a0c1bd03709'
    || value.page_kernel_parity !== true || value.page_parity !== false || value.executable !== false
    || !Array.isArray(value.combos) || value.combos.length !== 6) return false
  const keys = new Set<string>()
  let best = 0
  for (const c of value.combos) {
    if (!record(c) || !['oscillation', 'trend'].includes(String(c.strategy)) || !['1w', '1d', '60m'].includes(String(c.frequency))
      || !day(c.since) || c.since !== (c.frequency === '1w' ? '2024-06-01' : c.frequency === '1d' ? '2025-09-01' : '2026-04-01')
      || !integer(c.source_bars) || typeof c.is_best !== 'boolean') return false
    const key = `${c.strategy}:${c.frequency}`
    if (keys.has(key)) return false
    keys.add(key)
    if (c.summary === null) {
      if (typeof c.reason_code !== 'string' || c.score !== null || c.confidence !== null || c.is_best) return false
      if (!(c.through === null || day(c.through)) || !(c.input_sha256 === null || digest(c.input_sha256))) return false
      continue
    }
    const s = c.summary
    if (!record(s) || !decimal(s.cumulative_return) || !decimal(s.max_drawdown) || Number(s.max_drawdown) < 0
      || !integer(s.win_rate) || s.win_rate > 100 || !integer(s.trade_count) || !integer(s.terminal_valuation_count)
      || s.terminal_valuation_count > s.trade_count || !integer(s.segment_count) || s.segment_count < 1
      || !integer(s.warming_segment_count) || !day(c.through) || c.through < c.since || !digest(c.input_sha256)
      || c.source_bars < 11 || c.reason_code !== null) return false
    if (s.trade_count < 3) {
      if (c.score !== null || c.confidence !== null || c.is_best) return false
    } else if (!decimal(c.score) || Number(c.score) < 0 || Number(c.score) > 1
      || c.confidence !== (s.trade_count >= 10 ? 'high' : 'mid')) return false
    if (c.is_best) best++
  }
  const dailyTrend = value.combos.find(c => c.frequency === '1d' && c.strategy === 'trend')
  return validFourStep(value.four_step, dailyTrend, value.schema_version === 'newow_ai_analysis_v4')
    && best === (value.combos.some(c => record(c) && record(c.summary) && Number(c.summary.trade_count) >= 3) ? 1 : 0)
}

export async function getNewowAiAnalysis(product: string, asOf: string, options: { signal?: AbortSignal; request?: Transport; historicalSnapshot?: boolean } = {}): Promise<AiAnalysis> {
  if (options.historicalSnapshot) asOf = historicalAnalysisAsOf(asOf)
  const transport = options.request ?? (async (path, config) => {
    const { default: request } = await import('./request.ts')
    return request.get<never, unknown>(path, config)
  })
  let value: unknown
  try {
    value = await transport('/market/newow/ai-analysis', { params: { product, as_of: asOf }, signal: options.signal, timeout: 35000 })
  } catch (error) {
    const response = record(error) && record(error.response) ? error.response : null
    const detail = response && record(response.data) && record(response.data.detail) ? response.data.detail : null
    throw new Error(response?.status === 429 && detail?.code === 'NEWOW_RESOURCE_BUSY'
      ? 'NEWOW_RESOURCE_BUSY' : 'NEWOW_AI_REQUEST_UNAVAILABLE')
  }
  if (!validateAiAnalysis(value, product, asOf)) throw new Error('NEWOW_AI_RESPONSE_INVALID')
  return value
}

export function historicalAnalysisAsOf(asOf: string): string {
  const instant = previewInstant(asOf)
  if (instant === null) return asOf
  return instant > previewInstant('2026-09-24T07:00:00.000001Z')! ? '2026-09-24T07:00:00.000001Z' : asOf
}
