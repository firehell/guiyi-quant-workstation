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
  live_realtime_repainting: {
    kind: 'observation-only',
    label: 'HTDY 实时重绘观察',
    title: 'HTDY first-seen 重绘观察；不是普通 live-confirmed、通知或交易信号',
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

export function signalSourceDataMode(mode?: string | null): 'live' | 'historical' {
  return mode === 'live_confirmed' || mode === 'live_realtime_repainting'
    ? 'live'
    : 'historical'
}

export function signalResearchIdentity(
  record: Pick<
    StrategySignalRecord,
    'strategy_code' | 'strategy_id' | 'strategy_version_id' | 'strategy_version' | 'features' | 'watchlist_code'
  > & { source_mode?: string | null },
) {
  const strategyCode = record.strategy_code || record.strategy_id
  const strategyVersion = record.strategy_version_id || record.strategy_version
  return {
    strategy: `${strategyCode} · ${strategyVersion}`,
    observation: resolveSignalSourceMode(record),
  }
}

export function signalQualification(
  record: Pick<StrategySignalRecord, 'data_role' | 'quality_status' | 'research_only'>,
) {
  const status = String(record.quality_status?.status || 'unknown').toLowerCase()
  if (record.data_role !== 'primary' || status === 'failed') {
    return {
      status: 'failed',
      label: '研究输入不合格',
      note: `${record.data_role || 'unknown'} 数据 / ${status} 质量不可作为当前研究输入`,
    }
  }
  if (status === 'passed') {
    return {
      status: 'passed',
      label: '研究输入合格',
      note: 'primary 数据质量已通过；信号仍仅供研究观察',
    }
  }
  return {
    status: status === 'warning' ? 'warning' : 'unknown',
    label: '研究输入需复核',
    note: `primary 数据质量为 ${status}；使用前需检查质量证据`,
  }
}
