/** Validate the optional public diagnostic envelope before rendering any location. */
const REASONS = {
  REPLAY_PREFIX_MISSING: '同合约预热历史缺失',
  REPLAY_ENDPOINTS_MISSING: '同合约历史 Bar 缺失',
  TRADING_CALENDAR_MISSING: '交易日历缺失',
  TRADING_SESSION_MISSING: '交易时段缺失',
  HISTORICAL_SESSION_FACT_MISSING: '历史交易时段事实缺失',
  CONTRACT_METADATA_MISSING: '合约元数据缺失',
  MAIN_CONTRACT_MAP_MISSING: '主力合约映射缺失',
  DATASET_OR_PARTITION_MISSING: '行情数据集或分区缺失',
  COMPLETE_PERIOD_MISSING: '已完成周期数据缺失',
  CONTRACT_ACTIVE_WINDOW_MISSING: '合约有效区间缺失',
  PRODUCT_WINDOW_START_MISSING: '品种历史起点缺失',
  REPLAY_ORDER_INVALID: '历史 Bar 顺序或重复校验失败',
  REPLAY_ENDPOINTS_EXTRA: '历史 Bar 与权威时段不一致',
  REPLAY_CUTOFF_MISMATCH: '历史截止时间与权威时段不一致',
  METADATA_IDENTITY_INVALID: '元数据身份校验失败',
  DATA_INTEGRITY_INVALID: '行情完整性校验失败',
  SOURCE_NONPOSITIVE_PRICE: '原始行情包含非正价格，当前指标不支持此输入',
} as const

export interface NewowDataDiagnostic {
  readonly reason: keyof typeof REASONS
  readonly context: Readonly<Record<string, string | number>>
  readonly historicalCandidateRecoverable: boolean
}

export function newowErrorDisplay(error: string | null): string | null {
  if (error === null) return null
  const labels: Record<string, string> = {
    NEWOW_DATA_UNAVAILABLE: '数据暂不可用，可重试本面板',
    NEWOW_API_UNAVAILABLE: '服务暂不可用，可重试本面板',
    NEWOW_INTERNAL_ERROR: '服务内部校验失败，可重试本面板',
    NEWOW_HISTORICAL_SNAPSHOT_UNAVAILABLE: '限定范围内未找到可用历史快照，需检查数据后重试',
    NEWOW_HISTORICAL_RESOLUTION_TIMEOUT: '历史快照检查超时，可重试',
    NEWOW_COMPLETE_TRADING_DAY_MISSING: '尚无已完成交易日数据，可重试本面板',
    NEWOW_COMPLETE_PERIOD_MISSING: '尚无已完成周期数据，可重试本面板',
  }
  return Object.hasOwn(labels, error) ? `${labels[error]}（${error}）` : error
}

export function parseNewowDataDiagnostic(value: unknown): NewowDataDiagnostic | null {
  if (!record(value) || typeof value.reason !== 'string' || !Object.hasOwn(REASONS, value.reason)
    || !record(value.context) || typeof value.historical_candidate_recoverable !== 'boolean') return null
  const reason = value.reason as keyof typeof REASONS
  const context: Record<string, string | number> = {}
  for (const [key, item] of Object.entries(value.context)) {
    if (key === 'symbol' && typeof item === 'string' && /^[a-z]{1,8}$/.test(item)) context[key] = item
    else if (key === 'contract' && typeof item === 'string' && /^[A-Za-z]{1,8}[0-9]{3,4}$/.test(item)) context[key] = item
    else if (key === 'frequency' && typeof item === 'string' && ['1m', '5m', '15m', '30m', '60m', '1d', '1w'].includes(item)) context[key] = item
    else if (['expected_count', 'actual_count', 'missing_count'].includes(key) && typeof item === 'number' && Number.isSafeInteger(item) && item >= 0 && item <= 1e9) context[key] = item
    else if (['trading_day', 'first_missing_day'].includes(key) && typeof item === 'string' && validDay(item)) context[key] = item
    else if (['cutoff', 'first_missing_at'].includes(key) && typeof item === 'string' && item.length <= 40 && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})$/.test(item) && validDay(item.slice(0, 10)) && Number.isFinite(Date.parse(item))) context[key] = item
  }
  // The server flag cannot make integrity or source constraints recoverable.
  return Object.freeze({ reason, context: Object.freeze(context), historicalCandidateRecoverable: value.historical_candidate_recoverable && reason.endsWith('_MISSING') })
}

export function formatNewowDataDiagnostic(diagnostic: NewowDataDiagnostic): string {
  const { context, reason } = diagnostic
  const location = [context.symbol, context.contract, context.frequency, context.first_missing_at ?? context.first_missing_day ?? context.trading_day ?? context.cutoff].filter((item) => item !== undefined).join(' · ')
  const counts = context.missing_count === undefined ? '' : `，缺失 ${context.missing_count} 根`
  const hint = reason === 'SOURCE_NONPOSITIVE_PRICE'
    ? '保留原始记录；需先确认指标支持范围，重复下载不会解决此限制。'
    : diagnostic.historicalCandidateRecoverable
      ? '可重试本面板，或主动查看最近可用历史快照；数据修复需单独处理。'
      : '请检查数据身份、时段与完整性；修正后重试本面板。'
  return `${REASONS[reason]}${location ? `（${location}${counts}）` : counts}。${hint}`
}

function validDay(value: string): boolean {
  return /^\d{4}-\d{2}-\d{2}$/.test(value) && Number.isFinite(Date.parse(`${value}T00:00:00Z`)) && new Date(`${value}T00:00:00Z`).toISOString().slice(0, 10) === value
}

function record(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
}
