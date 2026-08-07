export type ResearchSourceType = 'strategy_signal' | 'signal_event'

export interface ResearchContext {
  reviewId?: number | null
  signalId?: number | null
  signalEventId?: number | null
  sourceType?: ResearchSourceType | null
  sourceId?: number | null
  symbol?: string | null
  contract?: string | null
  period?: string | null
  time?: string | null
  dataMode?: 'historical' | null
  returnRoute?: string | null
}

type QueryValue = string | string[] | null | undefined

function first(value: QueryValue): string | null {
  const selected = Array.isArray(value) ? value[0] : value
  return typeof selected === 'string' && selected.trim() ? selected.trim() : null
}

function positiveId(value: QueryValue): number | null {
  const parsed = Number(first(value))
  return Number.isInteger(parsed) && parsed > 0 ? parsed : null
}

export function safeReturnRoute(value: unknown): string | null {
  if (typeof value !== 'string') return null
  const route = value.trim()
  if (!route.startsWith('/') || route.startsWith('//') || route.includes('\\')) return null
  if (route.split(/[/?]/).filter(Boolean)[0] === 'backtest') return null
  return route
}

export function currentReturnRoute(path: string, query: Record<string, QueryValue>): string {
  const params = new URLSearchParams()
  Object.entries(query).forEach(([key, raw]) => {
    const value = first(raw)
    if (value && key !== 'return_route') params.set(key, value)
  })
  const suffix = params.toString()
  return `${path}${suffix ? `?${suffix}` : ''}`
}

export function parseResearchContext(query: Record<string, QueryValue>): ResearchContext {
  const sourceTypeValue = first(query.source_type)
  const sourceType = sourceTypeValue === 'signal_event' || sourceTypeValue === 'strategy_signal'
    ? sourceTypeValue
    : null
  const dataModeValue = first(query.data_mode)
  return {
    reviewId: positiveId(query.review_id),
    signalId: positiveId(query.signal_id),
    signalEventId: positiveId(query.signal_event_id),
    sourceType,
    sourceId: positiveId(query.source_id),
    symbol: first(query.symbol),
    contract: first(query.contract),
    period: first(query.period) || first(query.interval),
    time: first(query.time) || first(query.datetime),
    dataMode: dataModeValue === 'historical' ? 'historical' : null,
    returnRoute: safeReturnRoute(first(query.return_route)),
  }
}

export function buildChartResearchQuery(context: ResearchContext): Record<string, string | undefined> {
  return compactQuery({
    symbol: context.symbol || undefined,
    contract: context.contract || undefined,
    period: context.period || undefined,
    time: context.time || undefined,
    data_mode: context.dataMode || undefined,
    review_id: context.reviewId ? String(context.reviewId) : undefined,
    signal_id: context.signalId ? String(context.signalId) : undefined,
    signal_event_id: context.signalEventId ? String(context.signalEventId) : undefined,
    return_route: safeReturnRoute(context.returnRoute) || undefined,
  })
}

export function buildCreatedReviewRouteQuery(
  reviewId: number,
  context: ResearchContext,
): Record<string, string | undefined> {
  return {
    ...buildReviewResearchQuery(context),
    review_id: String(reviewId),
  }
}

export function buildReviewResearchQuery(context: ResearchContext): Record<string, string | undefined> {
  if (context.signalEventId || (context.sourceType === 'signal_event' && context.sourceId)) {
    const eventId = context.signalEventId || context.sourceId
    return compactQuery({
      source_type: 'signal_event',
      source_id: String(eventId),
      signal_id: context.signalId ? String(context.signalId) : undefined,
      signal_event_id: String(eventId),
      return_route: safeReturnRoute(context.returnRoute) || undefined,
    })
  }
  if (context.signalId || (context.sourceType === 'strategy_signal' && context.sourceId)) {
    const signalId = context.signalId || context.sourceId
    return compactQuery({
      source_type: 'strategy_signal',
      source_id: String(signalId),
      signal_id: String(signalId),
      return_route: safeReturnRoute(context.returnRoute) || undefined,
    })
  }
  return compactQuery({
    review_id: context.reviewId ? String(context.reviewId) : undefined,
    return_route: safeReturnRoute(context.returnRoute) || undefined,
  })
}

export function buildSignalEventReviewQuery(
  eventId: number,
  signalId: number | null | undefined,
  returnRoute: string | null | undefined,
): Record<string, string | undefined> {
  return buildReviewResearchQuery({
    sourceType: 'signal_event',
    sourceId: eventId,
    signalEventId: eventId,
    signalId,
    returnRoute,
  })
}

function compactQuery(query: Record<string, string | undefined>): Record<string, string | undefined> {
  return Object.fromEntries(Object.entries(query).filter(([, value]) => value !== undefined))
}
