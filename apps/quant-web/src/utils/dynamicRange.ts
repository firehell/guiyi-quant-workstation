import type { BarData } from '../types/market.ts'

export interface DynamicRangePoint {
  time: string; contract: string; open: number; high: number; low: number; close: number
  regime: 'RANGE' | 'TREND_UP' | 'TREND_DOWN' | 'UNKNOWN'
  phase: string; reason: string | null; er: number | null; chop: number | null
  trend_candidate: boolean; break_side: string | null
  box: { box_id: string; confirmed_at: string; lower: number; upper: number; atr_reference: number; revision: number } | null
}
export const regimeLabel = { RANGE: '震荡', TREND_UP: '上涨趋势', TREND_DOWN: '下跌趋势', UNKNOWN: '不可用' }
export const phaseLabel: Record<string, string> = { SEARCHING: '寻找箱体', FORMING: '形成中', RANGE_ACTIVE: '箱内', RANGE_EXPANDING: '有限扩展', BOUNDARY_TEST: '边界试探', BREAK_PENDING: '突破待确认', BREAK_CONFIRMED: '突破确认', BREAK_FAILED: '假突破' }
export function pointKey(contract: string, time: string) { return `${contract}:${Date.parse(time)}` }
export function matchesRangeBar(p: DynamicRangePoint, b: BarData) {
  return p.contract === b.physicalContract && Date.parse(p.time) === Date.parse(b.time)
    && p.open === b.open && p.high === b.high && p.low === b.low && p.close === b.close
}

/** Fail closed on wire identity, gaps or source disagreement; never backfill estimates. */
export function normalizeRangeResponse(raw: unknown, symbol: string, frequency: string, bars: BarData[]): DynamicRangePoint[] {
  const r = raw as Record<string, any>
  if (!r || r.version !== 'subing_dynamic_range_v2' || r.trend_version !== 'subing_ema21_ols5_atr14_v2'
      || r.profile !== 'bounded_confirmed' || r.symbol !== symbol || r.frequency !== frequency
      || r.contract !== bars[0]?.physicalContract || !Array.isArray(r.points) || r.points.length !== bars.length
      || !/^[a-f0-9]{64}$/.test(r.source_hash) || !Number.isFinite(Date.parse(r.prefix_start))
      || Date.parse(r.prefix_start) > Date.parse(bars[0].time)) throw new Error('DYNAMIC_RANGE_SOURCE_MISMATCH')
  const numeric = (v: unknown): number => {
    if ((typeof v !== 'string' && typeof v !== 'number') || v === '' || !Number.isFinite(Number(v))) throw new Error('DYNAMIC_RANGE_INVALID')
    return Number(v)
  }
  return r.points.map((wire: any, i: number) => {
    if (!wire || !(wire.regime in regimeLabel) || !(wire.phase in phaseLabel) || typeof wire.trend_candidate !== 'boolean'
        || !(wire.reason === null || typeof wire.reason === 'string')) throw new Error('DYNAMIC_RANGE_INVALID')
    const p: DynamicRangePoint = { ...wire, open: numeric(wire.open), high: numeric(wire.high), low: numeric(wire.low), close: numeric(wire.close),
      er: wire.er === null ? null : numeric(wire.er), chop: wire.chop === null ? null : numeric(wire.chop), box: null }
    if (wire.box !== null) {
      const b = wire.box
      if (!b || typeof b.box_id !== 'string' || !Number.isInteger(b.revision) || b.revision < 0
          || !Number.isFinite(Date.parse(b.confirmed_at)) || Date.parse(b.confirmed_at) > Date.parse(p.time)) throw new Error('DYNAMIC_RANGE_INVALID')
      p.box = { ...b, lower: numeric(b.lower), upper: numeric(b.upper), atr_reference: numeric(b.atr_reference) }
      if (p.box!.lower > p.box!.upper || p.box!.atr_reference <= 0) throw new Error('DYNAMIC_RANGE_INVALID')
    }
    if (!matchesRangeBar(p, bars[i])) throw new Error('DYNAMIC_RANGE_SOURCE_MISMATCH')
    return p
  })
}

export function mergeRangePoints(old: readonly DynamicRangePoint[], incoming: readonly DynamicRangePoint[]): DynamicRangePoint[] {
  const map = new Map(old.map(p => [pointKey(p.contract, p.time), p]))
  for (const p of incoming) {
    const key = pointKey(p.contract, p.time), previous = map.get(key)
    if (previous && JSON.stringify(previous) !== JSON.stringify(p)) throw new Error('DYNAMIC_RANGE_HISTORY_CHANGED')
    map.set(key, previous ?? p)
  }
  return [...map.values()].sort((a,b) => Date.parse(a.time)-Date.parse(b.time))
}


export interface RangeSourceProof { lifecycle_hash: string; partitions: Record<string,string> }
export function rangeSourceProof(raw: unknown): RangeSourceProof {
  const p = (raw as { source_proof?: RangeSourceProof })?.source_proof
  if (!p || !/^[a-f0-9]{64}$/.test(p.lifecycle_hash) || !p.partitions || typeof p.partitions !== 'object'
      || !Object.keys(p.partitions).length || Object.entries(p.partitions).some(([k,v])=>!/^\d{4}-\d{1,2}$/.test(k)||!/^[a-f0-9]{64}$/.test(v))) throw new Error('DYNAMIC_RANGE_SOURCE_MISMATCH')
  return {lifecycle_hash:p.lifecycle_hash,partitions:{...p.partitions}}
}
export function mergeRangeSource(old: RangeSourceProof | undefined, next: RangeSourceProof): RangeSourceProof {
  if (old && (old.lifecycle_hash!==next.lifecycle_hash || Object.entries(next.partitions).some(([k,v])=>old.partitions[k]!==undefined && old.partitions[k]!==v))) throw new Error('DYNAMIC_RANGE_SOURCE_CHANGED')
  return {lifecycle_hash:next.lifecycle_hash,partitions:{...old?.partitions,...next.partitions}}
}
