import { isRecordingTradingDay } from '../utils/newowRecording.ts'
import type {
  ReferenceIdentity, ReferencePage, ReferencePoint, ReferenceStreamInfo,
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
  if (!result || !['newow_recording_matrix_v1', 'newow_recording_matrix_v2', 'newow_recording_matrix_v3'].includes(result.version) || result.recording_mode !== 'forward_observation'
    || !Array.isArray(result.items)) throw new Error('REFERENCE_RESPONSE_INVALID')
  if (result.version !== 'newow_recording_matrix_v1') {
    const counts = [result.configured_count, result.enabled_count, result.observed_count, result.seeded_count]
    if (!Number.isSafeInteger(result.expected_count) || result.expected_count < 0
      || counts.some(value => !Number.isSafeInteger(value) || Number(value) < 0 || Number(value) > result.expected_count)
      || result.items.some(item => !item || !(result.version === 'newow_recording_matrix_v3' ? ['canonical_completed', 'completed_live'] : ['canonical_completed']).includes(item.expected_source ?? '')
        || !['READY', 'UNKNOWN'].includes(item.endpoint_status ?? '')
        || ![null, 'historical_seed', 'observed'].includes(item.latest_state_source === undefined ? 'missing' : item.latest_state_source)
        || (item.latest_observed_trading_day !== undefined && item.latest_observed_trading_day !== null
          && !isRecordingTradingDay(item.latest_observed_trading_day))
        || (item.latest_reconciliation_status !== undefined
          && ![null, 'pending', 'matched', 'mismatch', 'not_applicable'].includes(item.latest_reconciliation_status))
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
