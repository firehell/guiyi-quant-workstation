import type { MarketRuntimeObservationInput } from '@/types/marketRuntimeObservation'
import type { RuntimeArchiveHealth, RuntimeHealth } from '@/types/runtime'

/** 标准归档任务号格式：archive:<symbol>:<contract>:<YYYY-MM-DD> */
const ARCHIVE_TASK_DAY_RE = /^archive:[^:]+:[^:]+:(\d{4}-\d{2}-\d{2})$/i

/**
 * 从归档健康信息中提取已归档交易日。
 * 不会把原始 latest_task_no 直接当作交易日标签使用。
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
 * 将 /api/runtime/health 响应映射为市场运行时观察输入。
 * 仅用于展示，不虚构合约、数据版本或健康状态。
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
