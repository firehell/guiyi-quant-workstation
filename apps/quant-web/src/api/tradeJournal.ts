import request from './request'

export type Direction = 'LONG' | 'SHORT'
export type Period = 'day' | 'week'
export type Source = 'SIMNOW' | 'SUBING_PAPER' | 'TQKQ_HISTORY' | 'NEWOW_REFERENCE' | 'RQALPHA_BACKTEST'
export type FilterSource = Source | 'MANUAL'
export type AssessmentKey = 'market' | 'entry' | 'management' | 'exit' | 'execution'
export type Rating = 'MET' | 'PARTLY_MET' | 'MISSED' | 'UNASSESSED' | 'NOT_APPLICABLE'
export type PlanFields = {
  title: string
  direction: Direction | 'WATCH'
  frequencies: string[]
  market: string
  entry: string
  stop: string
  target: string
  sizing: string
  scenarios: string
}
export type Plan = {
  id: string
  trading_day: string
  product: string | null
  version: number
  content: PlanFields
}
export type CaseListItem = {
  id: string
  title: string
  trading_day: string
  product: string
  contract: string
  direction: Direction
  closed: boolean
  reviewed: boolean
  tags: string[]
}
export type Review = {
  dimensions: Partial<Record<AssessmentKey, { rating: Rating; tags: string[]; note: string }>>
  takeaway: string
  next_action: string
}
export type SummaryFields = {
  environment: string
  observations: string
  missed: string
  execution: string
  next_action: string
  case_ids: string[]
}
export type Evidence = {
  native_id: string
  occurred_at: string
  contract: string
  direction: Direction
  action: string
  price: string | null
  fee: string | null
  quantity: number | null
  exit_price?: string | null
  net_pnl?: string | null
  reference_return?: string | null
  gross_realized?: string | null
}
export type TimelineRow = {
  id: string
  kind: string
  occurred_at: string
  trading_day: string
  recorded_at: string
  removed_at: string | null
  removal_reason: string | null
  replaces_manual: string | null
  manual: { note: string; price: string | null; quantity: number | null } | null
  source: Source | null
  scope: string | null
  native_id: string | null
  evidence?: Evidence
  evidence_status?: string
}
type Version = { component_version: string }
export type Workspace = Version & {
  plans: Plan[]
  cases: CaseListItem[]
  summary: { version: number; content: SummaryFields } | null
  next_offset: number | null
}
export type Detail = Version & {
  case: Omit<CaseListItem, 'reviewed'> & { version: number; review: Review | null }
  plan: Plan | null
  timeline: TimelineRow[]
}
export type EvidenceList = Version & {
  scope: string | null
  scopes: string[]
  scope_labels: Record<string, string>
  status: string
  items: Evidence[]
  has_more: boolean
}

const root = '/trade-journal'
export const readJournal = (params: Record<string, string | number | undefined>, signal: AbortSignal) =>
  request.get<unknown, Workspace>(root, { params, signal })
export const readCase = (id: string, signal: AbortSignal) =>
  request.get<unknown, Detail>(root + '/cases/' + encodeURIComponent(id), { signal })
export const readEvidence = (params: Record<string, string | undefined>, signal: AbortSignal) =>
  request.get<unknown, EvidenceList>(root + '/evidence', { params, signal })
export const writeJournal = (path: string, body: object, idempotencyKey: string) =>
  request.put<unknown, Version & { id?: string; version?: number }>(root + path, body, {
    headers: { 'Idempotency-Key': idempotencyKey },
  })
