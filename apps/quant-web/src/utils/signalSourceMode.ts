import type { CapabilityKind } from '@/components/common/CapabilityBadge.vue'
import type { SignalEventRecord, StrategySignalRecord } from '@/types/signal'

export type KnownSignalSourceMode =
  | 'historical_scan'
  | 'jm_v1b_scan'
  | 'jm_v1b_historical_replay'
  | 'live_confirmed'
  | 'manual_api'
  | string

const SOURCE_MODE_META: Record<
  string,
  { kind: CapabilityKind; label: string; title: string }
> = {
  historical_scan: {
    kind: 'research-only',
    label: '历史扫描',
    title: '历史 bar 扫描；非 live-confirmed',
  },
  jm_v1b_scan: {
    kind: 'research-only',
    label: '历史研究扫描',
    title: 'JM V1-B 历史研究扫描；非 live-confirmed',
  },
  jm_v1b_historical_replay: {
    kind: 'historical-replay',
    label: '测试/回放',
    title: '历史 replay 测试数据；不是 live-confirmed',
  },
  live_confirmed: {
    kind: 'live-confirmed',
    label: 'Live 已确认',
    title: 'Live bar 已确认事件；仍非自动下单',
  },
  manual_api: {
    kind: 'observation-only',
    label: 'Manual API',
    title: '手工/API 注入；非扫描或 live 流水线',
  },
}

export function resolveSignalSourceMode(
  record: Pick<StrategySignalRecord, 'features' | 'watchlist_code'> & {
    source_mode?: string | null
  },
): KnownSignalSourceMode {
  const direct = record.source_mode || (record.features?.source_mode as string | undefined)
  if (direct) return direct
  if (record.watchlist_code === 'jm_v1b') return 'jm_v1b_scan'
  return 'historical_scan'
}

export function resolveEventSourceMode(event: SignalEventRecord): KnownSignalSourceMode {
  return event.source_mode || 'historical_scan'
}

export function sourceModeBadge(mode: string) {
  const meta = SOURCE_MODE_META[mode] || {
    kind: 'research-only' as CapabilityKind,
    label: mode || '未知来源',
    title: '未识别的 source_mode；默认按 research-only 理解',
  }
  return meta
}
