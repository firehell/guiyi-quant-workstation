import type { NewowTrendDetailResponse } from '../types/newow.ts'
import { normalizeNewowTrendDetailResponse } from '../utils/newowTypes.ts'

export interface NewowTrendDetailRequest {
  product: string
  from: string
  through: string
}

const NEWOW_CLIENT_ERROR_CODES = [
  'NEWOW_INVALID_PRODUCT',
  'NEWOW_INVALID_RANGE',
  'NEWOW_RANGE_TOO_LARGE',
] as const

const NEWOW_CONFLICT_ERROR_CODES = [
  'NEWOW_DATA_IDENTITY_INVALID',
  'NEWOW_DATA_UNAVAILABLE',
  'NEWOW_DATA_OUT_OF_ORDER',
] as const

export type NewowTrendDetailPublicApiErrorCode =
  | (typeof NEWOW_CLIENT_ERROR_CODES)[number]
  | (typeof NEWOW_CONFLICT_ERROR_CODES)[number]

export type NewowTrendDetailRequestErrorCode =
  | NewowTrendDetailPublicApiErrorCode
  | 'NEWOW_API_UNAVAILABLE'
  | 'NEWOW_RESPONSE_INVALID'

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
    throw new NewowTrendDetailRequestError(publicApiCode(error) ?? 'NEWOW_API_UNAVAILABLE')
  }

  try {
    return normalizeNewowTrendDetailResponse(payload, {
      symbol: params.product,
      from: params.from,
      through: params.through,
    })
  } catch {
    throw new NewowTrendDetailRequestError('NEWOW_RESPONSE_INVALID')
  }
}

function publicApiCode(error: unknown): NewowTrendDetailPublicApiErrorCode | null {
  try {
    if (!isRecord(error)) return null
    const response = error.response
    if (!isRecord(response) || (response.status !== 409 && response.status !== 422)) return null
    const data = response.data
    if (!isRecord(data)) return null
    const detail = data.detail
    if (!isRecord(detail) || typeof detail.code !== 'string') return null
    const allowed = response.status === 422
      ? NEWOW_CLIENT_ERROR_CODES
      : NEWOW_CONFLICT_ERROR_CODES
    return (allowed as readonly string[]).includes(detail.code)
      ? detail.code as NewowTrendDetailPublicApiErrorCode
      : null
  } catch {
    return null
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
}
