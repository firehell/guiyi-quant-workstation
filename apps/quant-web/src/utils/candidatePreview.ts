import { previewInstant } from './candidatePreviewInstant.ts'

export const candidatePreview = Object.freeze({
  enabled: import.meta.env?.VITE_CANDIDATE_PREVIEW === '1',
  codeSha: import.meta.env?.VITE_PREVIEW_CODE_SHA || '',
  asOf: import.meta.env?.VITE_PREVIEW_AS_OF || '',
})

export function matchesPreviewIdentity(value: unknown, expected = candidatePreview): boolean {
  if (!value || typeof value !== 'object') return false
  const identity = value as Record<string, unknown>
  const expectedInstant = previewInstant(expected.asOf)
  return identity.mode === 'local_candidate_readonly'
    && identity.code_sha === expected.codeSha
    && typeof identity.as_of === 'string'
    && expectedInstant !== null && previewInstant(identity.as_of) === expectedInstant
    && identity.realtime === false
    && identity.candidate_origin === 'http://127.0.0.1:8010'
    && identity.status_origin === 'http://127.0.0.1:8000'
}
