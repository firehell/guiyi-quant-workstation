import type { NewowTrendDetailResponse } from '../types/newow.ts'
import { normalizeNewowTrendDetailResponse } from '../utils/newowTypes.ts'

export interface NewowTrendDetailRequest {
  product: string
  from: string
  through: string
}

export type NewowTrendDetailRequestErrorCode =
  | 'NEWOW_NETWORK_UNAVAILABLE'
  | 'NEWOW_API_UNAVAILABLE'
  | 'NEWOW_PAYLOAD_INVALID'

export class NewowTrendDetailRequestError extends Error {
  readonly code: NewowTrendDetailRequestErrorCode

  constructor(code: NewowTrendDetailRequestErrorCode) {
    super(code)
    this.name = 'NewowTrendDetailRequestError'
    this.code = code
  }
}

interface NewowRequestConfig {
  params: {
    product: string
    from: string
    through: string
    frequency: '1d'
    series_kind: 'actual_dominant'
  }
  signal?: AbortSignal
}

type NewowRequest = (path: string, config: NewowRequestConfig) => Promise<unknown>

export interface NewowTrendDetailRequestOptions {
  signal?: AbortSignal
  request?: NewowRequest
}

async function defaultRequest(path: string, config: NewowRequestConfig): Promise<unknown> {
  const { default: request } = await import('./request.ts')
  return request.get<never, unknown>(path, config)
}

export async function getNewowTrendDetail(
  params: NewowTrendDetailRequest,
  options: NewowTrendDetailRequestOptions = {},
): Promise<NewowTrendDetailResponse> {
  const request = options.request ?? defaultRequest
  let payload: unknown
  try {
    payload = await request('/market/newow/trend-detail', {
      params: {
        product: params.product,
        from: params.from,
        through: params.through,
        frequency: '1d',
        series_kind: 'actual_dominant',
      },
      signal: options.signal,
    })
  } catch (error) {
    if (error instanceof NewowTrendDetailRequestError) throw error
    throw new NewowTrendDetailRequestError(hasHttpResponse(error)
      ? 'NEWOW_API_UNAVAILABLE'
      : 'NEWOW_NETWORK_UNAVAILABLE')
  }

  try {
    return normalizeNewowTrendDetailResponse(payload, {
      symbol: params.product,
      from: params.from,
      through: params.through,
    })
  } catch {
    throw new NewowTrendDetailRequestError('NEWOW_PAYLOAD_INVALID')
  }
}

function hasHttpResponse(error: unknown): boolean {
  return error !== null
    && typeof error === 'object'
    && 'response' in error
    && (error as { response?: unknown }).response !== undefined
}
