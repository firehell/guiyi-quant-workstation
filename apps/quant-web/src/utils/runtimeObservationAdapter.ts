import type { MarketRuntimeObservationInput } from '@/types/marketRuntimeObservation'
import type { RuntimeArchiveHealth, RuntimeHealth } from '@/types/runtime'

/** Standard archive task_no: archive:<symbol>:<contract>:<YYYY-MM-DD> */
const ARCHIVE_TASK_DAY_RE = /^archive:[^:]+:[^:]+:(\d{4}-\d{2}-\d{2})$/i

/**
 * Extract archived trading day from archive health.
 * Never treats raw latest_task_no as a trading day label.
 */
export function parseArchivedTradingDay(
  archive: Pick<RuntimeArchiveHealth, 'latest_task_no'> | null | undefined,
): string | null {
  const taskNo = archive?.latest_task_no
  if (typeof taskNo !== 'string' || !taskNo.trim()) return null
  const match = ARCHIVE_TASK_DAY_RE.exec(taskNo.trim())
  return match?.[1] ?? null
}

/**
 * Map /api/runtime/health payload into Market Runtime Observation input.
 * Display-only; does not invent contracts, data versions, or healthy status.
 */
export function buildRuntimeHealthObservationInput(
  health: RuntimeHealth,
): MarketRuntimeObservationInput {
  const checkpoints = health.components.live_checkpoints
  const firstLag =
    checkpoints.recent_ingest[0]?.lag_seconds ??
    checkpoints.recent_aggregation[0]?.lag_seconds ??
    null

  return {
    data_mode: 'live',
    runtime_health_status: health.status,
    checkpoint_status: checkpoints.status,
    checkpoint_lag_seconds: firstLag,
    latency_ms:
      health.components.db.latency_ms ?? health.components.redis.latency_ms ?? null,
    archived_trading_day: parseArchivedTradingDay(health.components.archive),
  }
}
