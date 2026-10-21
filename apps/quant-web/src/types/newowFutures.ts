import type { FuturesVariant } from '../utils/newowFutures.ts'
export type FrozenRecord = Record<string, unknown>
export interface FuturesSnapshot {
  schema_version: 1
  run_id: string
  sha256: string
  metadata: FrozenRecord & { run_id: string; strategy_model: 'futures_bidir_v1'; strategy: FuturesVariant; product: string; frequency: string; scenario: string; as_of: string; status: string; input_snapshot_hash: string | null; execution_facts_hash: string | null; profile_id: string }
  summary: FrozenRecord
  reference: { summary: FrozenRecord; snapshot: FrozenRecord | null; actions: FrozenRecord[]; trades: FrozenRecord[]; equity: FrozenRecord[] }
  chart: { bars: FrozenRecord[]; frames: FrozenRecord[] }
  diagnostics: FrozenRecord | FrozenRecord[]
  preview?: FrozenRecord
}
export type FuturesPart = 'decisions' | 'fills' | 'trades' | 'equity' | 'reference-trades'
export interface FuturesPage { run_id: string; sha256: string; part: FuturesPart; items: FrozenRecord[]; total: number; offset: number; limit: number; next_offset: number | null }
export type FuturesCurveKind = 'equity' | 'reference-equity'
export interface FuturesCurve { run_id:string; sha256:string; kind:FuturesCurveKind; points:Array<{at:string;value:string|null;physical_contract?:string}>; total_points:number; status:'COMPLETED'|'CURVE_BOUNDARY_BUDGET_EXCEEDED'; sampled:boolean }
