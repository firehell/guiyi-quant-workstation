import type { SubingDailyWatchItem } from '../types/market.ts'

const REASON_LABELS: Readonly<Record<string, string>> = {
  D1_HISTORY_INSUFFICIENT: '日线历史不足',
  H1_HISTORY_INSUFFICIENT: '60m 历史不足',
  PRODUCT_METADATA_UNAVAILABLE: '品种元数据不可用',
  DATA_IDENTITY_MISMATCH: '数据身份不一致',
  DOMINANT_SEGMENT_UNAVAILABLE: '主力合约区间不可用',
  SOURCE_TRADING_DAY_MISSING: '来源交易日数据缺失',
}

export function visibleDailyWatchItems<T extends SubingDailyWatchItem>(
  items: readonly T[],
  expanded: boolean,
): T[] {
  return expanded ? [...items] : items.slice(0, 6)
}

export function subingDailyWatchReasonLabel(reasonCode: string): string {
  return REASON_LABELS[reasonCode] ?? '数据身份不可用'
}
