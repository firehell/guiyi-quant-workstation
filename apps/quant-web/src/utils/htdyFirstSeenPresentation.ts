export interface HtDyFirstSeenRecord {
  source_mode?: string | null
  strategy_name?: string | null
  strategy_code?: string | null
  strategy_version?: string | null
  actual_contract?: string | null
  contract?: string | null
  period?: string | null
  signal_time?: string | null
  bar_start?: string | null
  bar_end?: string | null
  features?: Record<string, unknown> | null
  payload?: Record<string, unknown> | null
}

export interface HtDyFirstSeenPresentation {
  isHtDyFirstSeen: true
  identity: string
  sourceMode: 'live_realtime_repainting'
  actualContract: string
  period: '15m'
  firstSeenAt: string
  bucketStart: string
  bucketEnd: string
  lineageSchema: 'signal_review_lineage_v2'
  observationOnly: true
  futureLooking: true
  repaintingAccepted: true
  firstSeenNoRetraction: true
  notificationReady: false
  autoOrder: false
}

export function buildHtDyFirstSeenPresentation(
  record: HtDyFirstSeenRecord,
): HtDyFirstSeenPresentation | null {
  const strategyCode = record.strategy_code || record.strategy_name
  const sourceMode = record.source_mode || readString(record.features, 'source_mode')
  const safety =
    readObject(record.payload, 'htdy_first_seen') ||
    record.features ||
    null
  const lineage =
    readObject(record.payload, 'formal_lineage') ||
    readObject(record.features, 'formal_lineage')
  const lineageContract = readObject(lineage, 'contract')
  const lineageBar = readObject(lineage, 'bar')
  const actualContract =
    record.actual_contract ||
    record.contract ||
    readString(lineageContract, 'actual_contract')
  const bucketStart = record.bar_start || readString(lineageBar, 'bar_start')
  const bucketEnd = record.bar_end || readString(lineageBar, 'bar_end')

  if (
    sourceMode !== 'live_realtime_repainting' ||
    strategyCode !== 'htdy_original_realtime_first_seen' ||
    record.strategy_version !== 'v1.0' ||
    record.period !== '15m' ||
    !actualContract ||
    !record.signal_time ||
    !bucketStart ||
    !bucketEnd ||
    readString(lineage, 'schema_version') !== 'signal_review_lineage_v2' ||
    safety?.observation_only !== true ||
    safety.future_looking !== true ||
    safety.repainting_accepted !== true ||
    safety.first_seen_no_retraction !== true ||
    safety.notification_ready !== false ||
    safety.auto_order !== false
  ) {
    return null
  }

  return {
    isHtDyFirstSeen: true,
    identity: 'htdy_original_realtime_first_seen / v1.0',
    sourceMode,
    actualContract,
    period: '15m',
    firstSeenAt: record.signal_time,
    bucketStart,
    bucketEnd,
    lineageSchema: 'signal_review_lineage_v2',
    observationOnly: true,
    futureLooking: true,
    repaintingAccepted: true,
    firstSeenNoRetraction: true,
    notificationReady: false,
    autoOrder: false,
  }
}

function readObject(
  value: Record<string, unknown> | null | undefined,
  key: string,
): Record<string, unknown> | null {
  const nested = value?.[key]
  return nested && typeof nested === 'object' && !Array.isArray(nested)
    ? nested as Record<string, unknown>
    : null
}

function readString(
  value: Record<string, unknown> | null | undefined,
  key: string,
): string | null {
  const nested = value?.[key]
  return typeof nested === 'string' && nested ? nested : null
}
