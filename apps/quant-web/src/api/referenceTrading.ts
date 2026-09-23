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
    params: { strategy: identity.strategy, product: identity.product, frequency: identity.frequency, mode: 'historical_replay' },
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
