import { previewInstant } from './candidatePreviewInstant.ts'

const DEFAULT_CANDIDATE_ORIGIN = 'http://127.0.0.1:8010'
const DEFAULT_STATUS_ORIGIN = 'http://127.0.0.1:8000'

export const candidatePreview = Object.freeze({
  enabled: import.meta.env?.VITE_CANDIDATE_PREVIEW === '1',
  codeSha: import.meta.env?.VITE_PREVIEW_CODE_SHA || '',
  asOf: import.meta.env?.VITE_PREVIEW_AS_OF || '',
  candidateOrigin: import.meta.env?.VITE_PREVIEW_CANDIDATE_ORIGIN || DEFAULT_CANDIDATE_ORIGIN,
})

export type PreviewIdentityExpected = {
  enabled?: boolean
  codeSha: string
  asOf: string
  candidateOrigin?: string
}

export function candidateOriginHost(origin = candidatePreview.candidateOrigin): string {
  return origin.replace(/^https?:\/\//, '')
}

export function matchesPreviewIdentity(
  value: unknown,
  expected: PreviewIdentityExpected = candidatePreview,
): boolean {
  if (!value || typeof value !== 'object') return false
  const identity = value as Record<string, unknown>
  const expectedInstant = previewInstant(expected.asOf)
  const expectedOrigin = expected.candidateOrigin || DEFAULT_CANDIDATE_ORIGIN
  return identity.mode === 'local_candidate_readonly'
    && identity.code_sha === expected.codeSha
    && typeof identity.as_of === 'string'
    && expectedInstant !== null && previewInstant(identity.as_of) === expectedInstant
    && identity.realtime === false
    && identity.candidate_origin === expectedOrigin
    && identity.status_origin === DEFAULT_STATUS_ORIGIN
}
