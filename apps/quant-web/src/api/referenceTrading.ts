import { isRecordingTradingDay } from '../utils/newowRecording.ts'
import type {
  MarketAfterClosePresentation, MarketAfterCloseReference, MarketAfterCloseSection, MarketAfterCloseSectionQuery, ReferenceIdentity, ReferencePage, ReferencePoint, ReferenceStreamInfo,
  ReferenceSummary, ReferenceTradeView, ReferenceWindow,
} from '../types/referenceTrading.ts'

export interface ReferenceRequestOptions {
  signal?: AbortSignal
  request?: (url: string, options: { params: Record<string, unknown>; signal?: AbortSignal }) => Promise<unknown>
}

function transport(options: ReferenceRequestOptions) {
  return options.request ?? (async (url: string, config: { params: Record<string, unknown>; signal?: AbortSignal }) => {
    const { default: request } = await import('./request.ts')
    return request.get<never, unknown>(url, config)
  })
}

export async function getReferenceStreams(identity: ReferenceIdentity, options: ReferenceRequestOptions = {}): Promise<ReferenceStreamInfo[]> {
  const result = await transport(options)('/reference-trading/streams', {
    params: { strategy: identity.strategy, product: identity.product, frequency: identity.frequency, mode: identity.mode ?? 'historical_replay' },
    signal: options.signal,
  }) as { items?: unknown }
  if (!result || !Array.isArray(result.items)) throw new Error('REFERENCE_RESPONSE_INVALID')
  return result.items as ReferenceStreamInfo[]
}

export async function getMarketAfterCloseReference(identity: ReferenceIdentity, options: ReferenceRequestOptions = {}): Promise<MarketAfterCloseReference | null> {
  const value = await transport(options)('/reference-trading/newow/after-close', {
    params: { strategy: identity.strategy, product: identity.product, frequency: identity.frequency },
    signal: options.signal,
  }) as { result?: MarketAfterCloseReference | null }
  if (!value || !Object.hasOwn(value, 'result')) throw new Error('REFERENCE_RESPONSE_INVALID')
  return value.result ?? null
}

export async function getMarketAfterClosePresentation(
  source: MarketAfterCloseReference, snapshot: string, span: { since: string; through: string; from: string; to: string },
  options: ReferenceRequestOptions = {},
): Promise<MarketAfterClosePresentation> {
  const value = await transport(options)('/reference-trading/newow/after-close/presentation', {
    params: { stream_id: source.stream_id, since: span.since, through: span.through, cutoff: source.cutoff,
      snapshot, bar_from: span.from, bar_through: span.to },
    signal: options.signal,
  }) as MarketAfterClosePresentation
  if (!value || value.snapshot !== snapshot || !Array.isArray(value.frames)) throw new Error('REFERENCE_RESPONSE_INVALID')
  return value
}

export async function getMarketAfterCloseSection(
  query: MarketAfterCloseSectionQuery, options: ReferenceRequestOptions = {},
): Promise<MarketAfterCloseSection> {
  const { identity, section, asOf } = query
  const response = await transport(options)('/reference-trading/newow/after-close/section', {
    params: {
      product: identity.product, strategy: identity.strategy, frequency: identity.frequency, section,
      ...(query.section === 'auxiliary' ? { component: query.component } : {}),
    },
    signal: options.signal,
  }) as { status?: unknown; receipt?: unknown; reference?: Pick<MarketAfterCloseReference, 'stream_id' | 'revision_id' | 'seq'>; chart?: unknown; result?: unknown } | null
  const receipt = response?.receipt
  const validReceipt = typeof receipt === 'string' && /^[0-9a-f]{64}$/.test(receipt)
  if (!response || (!validReceipt && receipt !== null)) throw new Error('REFERENCE_RESPONSE_INVALID')
  const { status } = response
  if (status === 'pending' || status === 'unavailable') {
    if (response.chart !== null || response.result !== null) throw new Error('REFERENCE_RESPONSE_INVALID')
    return { status, receipt: validReceipt ? receipt : null, chart: null, result: null }
  }
  if (status !== 'ready' || !validReceipt) throw new Error('REFERENCE_RESPONSE_INVALID')
  const { normalizeNewowProductResponse } = await import('../utils/newowProductTypes.ts')
  const chart = normalizeNewowProductResponse(response.chart, { identity, asOf, section: 'chart' })
  const result = normalizeNewowProductResponse(response.result, query)
  if (chart.section !== 'chart' || (result.section !== 'auxiliary' && result.section !== 'comparator')
    || !chart.meta.snapshot_token || result.meta.snapshot_token !== chart.meta.snapshot_token
    || result.meta.data_revision_identity !== chart.meta.data_revision_identity) {
    throw new Error('REFERENCE_SNAPSHOT_CHANGED')
  }
  return { status, receipt, reference: response.reference, chart, result }
}

export async function getReferenceTrades(
  streamId: string, window: ReferenceWindow,
  options: ReferenceRequestOptions & { snapshot?: string; cursor?: string; limit?: number } = {},
): Promise<ReferencePage<ReferenceTradeView>> {
  return transport(options)(`/reference-trading/streams/${encodeURIComponent(streamId)}/trades`, {
    params: { since: window.since, through: window.through, ...(window.cutoff ? { cutoff: window.cutoff } : {}),
      ...(options.snapshot ? { snapshot: options.snapshot } : {}), ...(options.cursor ? { cursor: options.cursor } : {}),
      limit: options.limit ?? 50 },
    signal: options.signal,
  }) as Promise<ReferencePage<ReferenceTradeView>>
}

export async function getReferenceSummary(
  streamId: string, window: ReferenceWindow, snapshot: string,
  options: ReferenceRequestOptions = {},
): Promise<ReferenceSummary> {
  return transport(options)(`/reference-trading/streams/${encodeURIComponent(streamId)}/summary`, {
    params: { since: window.since, through: window.through, ...(window.cutoff ? { cutoff: window.cutoff } : {}), snapshot },
    signal: options.signal,
  }) as Promise<ReferenceSummary>
}

export async function getReferencePoints(
  streamId: string, kind: 'signals' | 'indicators', window: ReferenceWindow,
  snapshot: string, options: ReferenceRequestOptions & { cursor?: string; limit?: number } = {},
): Promise<ReferencePage<ReferencePoint>> {
  return transport(options)(`/reference-trading/streams/${encodeURIComponent(streamId)}/${kind}`, {
    params: { since: window.since, through: window.through, ...(window.cutoff ? { cutoff: window.cutoff } : {}), snapshot,
      ...(options.cursor ? { cursor: options.cursor } : {}), limit: options.limit ?? 200 },
    signal: options.signal,
  }) as Promise<ReferencePage<ReferencePoint>>
}

export async function getNewowRecordingMatrix(options: ReferenceRequestOptions = {}): Promise<import('../types/referenceTrading.ts').NewowRecordingMatrix> {
  const result = await transport(options)('/reference-trading/newow/matrix', { params: {}, signal: options.signal }) as import('../types/referenceTrading.ts').NewowRecordingMatrix
  if (!result || !['newow_recording_matrix_v1', 'newow_recording_matrix_v2', 'newow_recording_matrix_v3', 'newow_recording_matrix_v4'].includes(result.version) || result.recording_mode !== 'forward_observation'
    || !Array.isArray(result.items)) throw new Error('REFERENCE_RESPONSE_INVALID')
  if (result.version !== 'newow_recording_matrix_v1') {
    const counts = [result.configured_count, result.enabled_count, result.observed_count, result.seeded_count]
    if (!Number.isSafeInteger(result.expected_count) || result.expected_count < 0
      || counts.some(value => !Number.isSafeInteger(value) || Number(value) < 0 || Number(value) > result.expected_count)
      || result.items.some(item => !item || !(['newow_recording_matrix_v3', 'newow_recording_matrix_v4'].includes(result.version) ? ['canonical_completed', 'completed_live'] : ['canonical_completed']).includes(item.expected_source ?? '')
        || !['READY', 'UNKNOWN'].includes(item.endpoint_status ?? '')
        || ![null, 'historical_seed', 'observed'].includes(item.latest_state_source === undefined ? 'missing' : item.latest_state_source)
        || (item.latest_observed_trading_day !== undefined && item.latest_observed_trading_day !== null
          && !isRecordingTradingDay(item.latest_observed_trading_day))
        || (item.latest_reconciliation_status !== undefined
          && ![null, 'pending', 'matched', 'source_revised', 'mismatch', 'not_applicable'].includes(item.latest_reconciliation_status))
        || ![item.expected_through, item.observed_through, item.historical_computed_through, item.last_observed_at]
          .every(value => value === null || (typeof value === 'string' && Number.isFinite(Date.parse(value)))))) {
      throw new Error('REFERENCE_RESPONSE_INVALID')
    }
  }
  return result
}

export async function getNewowRecordingRecords(streamId: string, window: ReferenceWindow,
  options: ReferenceRequestOptions & { snapshot?: string; signalCursor?: string; stateCursor?: string } = {},
): Promise<{ signals: ReferencePage<ReferencePoint>; states: ReferencePage<ReferencePoint> }> {
  const snapshot = options.snapshot ?? (await getReferenceTrades(streamId, window, { ...options, limit: 1 })).snapshot
  const [signals, states] = await Promise.all([
    getReferencePoints(streamId, 'signals', window, snapshot, { ...options, cursor: options.signalCursor, limit: 50 }),
    getReferencePoints(streamId, 'indicators', window, snapshot, { ...options, cursor: options.stateCursor, limit: 50 }),
  ])
  if (signals.snapshot !== snapshot || states.snapshot !== snapshot || signals.revision_id !== states.revision_id || signals.seq !== states.seq) throw new Error('SNAPSHOT_CONFLICT')
  return { signals, states }
}

export async function getForwardReferencePanel(streamId: string, window: ReferenceWindow, options: ReferenceRequestOptions = {}) {
  return transport(options)(`/reference-trading/streams/${encodeURIComponent(streamId)}/panel`, {
    params: { since: window.since, through: window.through, ...(window.cutoff ? { cutoff: window.cutoff } : {}) }, signal: options.signal,
  }) as Promise<import('../types/referenceTrading.ts').ForwardReferencePanel>
}
