import type { AxiosResponse } from 'axios'
import request, { type ConditionalRequestConfig } from './request'
import { createConditionalResource } from '../utils/homeConditionalResource.ts'
export function createConditionalHomeRead<T>(url: string, normalize: (value: unknown) => T) {
  return createConditionalResource(async etag => {
    const config: ConditionalRequestConfig = { preserveResponse: true, headers: etag ? { 'If-None-Match': etag } : {}, validateStatus: status => status === 200 || status === 304 }
    const response = await request.get<never, AxiosResponse<unknown>>(url, config)
    return { status: response.status, data: response.data, etag: typeof response.headers.etag === 'string' ? response.headers.etag : undefined }
  }, normalize)
}
