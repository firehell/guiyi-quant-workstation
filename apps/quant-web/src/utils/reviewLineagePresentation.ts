import type { ReviewCanonicalLineage, ReviewFormalLineage, ReviewObservationLineage } from '@/types/review'
import { presentCanonicalInputIdentity } from './dataCoreV2Consumer.ts'

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function isWindow(value: unknown): value is { start: string | null; end: string | null } {
  return isRecord(value)
    && (typeof value.start === 'string' || value.start === null)
    && (typeof value.end === 'string' || value.end === null)
}

export function isCanonicalReviewLineage(
  lineage: unknown,
): lineage is ReviewCanonicalLineage {
  return isRecord(lineage)
    && lineage.schema_version === 'review_canonical_lineage_v1'
    && typeof lineage.source_type === 'string'
    && typeof lineage.source_id === 'number'
    && typeof lineage.input_digest === 'string'
    && Array.isArray(lineage.dataset_keys)
    && Array.isArray(lineage.manifest_digests)
    && isWindow(lineage.window)
    && isWindow(lineage.source_window)
    && isRecord(lineage.input_identity)
}

function isObservationReviewLineage(value: unknown): value is ReviewObservationLineage {
  return isRecord(value)
    && value.schema_version === 'review_source_lineage_v1'
    && typeof value.source_type === 'string'
    && typeof value.source_id === 'number'
}

function sourceWindow(start?: string | null, end?: string | null) {
  return `${start || '-'} → ${end || '-'}`
}

/** Render each backend lineage schema explicitly, without promoting observation lineage. */
export function presentReviewLineage(lineage: ReviewFormalLineage | unknown) {
  if (isCanonicalReviewLineage(lineage)) {
    const canonical = presentCanonicalInputIdentity(lineage.input_identity)
    if (canonical.status === 'unavailable') {
      return {
        kind: 'invalid' as const,
        schemaVersion: lineage.schema_version,
        label: 'Invalid canonical lineage (not trusted as canonical history)',
        reason: canonical.warning,
        sourceWindow: sourceWindow(lineage.source_window.start, lineage.source_window.end),
      }
    }
    return {
      kind: 'canonical' as const,
      schemaVersion: lineage.schema_version,
      canonical,
      inputDigest: lineage.input_digest,
      requestedWindow: sourceWindow(lineage.window.start, lineage.window.end),
      sourceWindow: sourceWindow(lineage.source_window.start, lineage.source_window.end),
    }
  }

  if (!isObservationReviewLineage(lineage)) {
    return {
      kind: 'invalid' as const,
      schemaVersion: isRecord(lineage) && typeof lineage.schema_version === 'string' ? lineage.schema_version : 'unavailable',
      label: 'Invalid review lineage (not trusted as canonical history)',
      reason: 'unsupported or malformed review lineage schema',
      sourceWindow: sourceWindow(),
    }
  }
  const bar = isRecord(lineage.bar) ? lineage.bar : null
  const mode = lineage.source_mode || bar?.confirmation_mode || 'live_observation'
  return {
    kind: 'observation' as const,
    schemaVersion: lineage.schema_version,
    label: 'Live observation lineage (legacy, not canonical history)',
    sourceMode: mode,
    sourceWindow: sourceWindow(
      typeof bar?.bar_start === 'string' ? bar.bar_start : null,
      typeof bar?.bar_end === 'string' ? bar.bar_end : null,
    ),
    sourceSnapshotSchemaVersion: lineage.source_snapshot_schema_version || 'unavailable',
  }
}
