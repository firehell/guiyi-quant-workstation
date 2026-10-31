import type { HtdySnapshot } from '../types/htdySnapshot.ts'
const instant=(value:unknown)=>typeof value==='string' && /(?:Z|[+-]\d\d:\d\d)$/.test(value) && Number.isFinite(Date.parse(value))
const decimal=(v:unknown)=>typeof v==='string' && /^[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?$/.test(v) && Number.isFinite(Number(v))
export function normalizeHtdySnapshot(raw:unknown, product:string, snapshot?:string):HtdySnapshot {
 const v=raw as HtdySnapshot
 if(!v || v.schema_version!=='htdy_historical_reference_v1' || v.product.toLowerCase()!==product.toLowerCase() || v.frequency!=='60m' || v.recording_mode!=='historical_replay'
 || !/^[a-f0-9]{64}$/.test(v.snapshot_id) || snapshot && snapshot!==v.snapshot_id || !instant(v.generated_at) || !instant(v.computed_through)
 || !/^[a-f0-9]{64}$/.test(v.source_token) || v.reference_model_version!=='htdy_historical_window32_reverse_close_v1'
 || v.executable!==false || v.auto_order!==false || !Array.isArray(v.formula_versions) || !v.formula_versions.length
 || !Array.isArray(v.trades) || v.trades.length>200 || !Array.isArray(v.actions) || v.actions.length>20000 || !Array.isArray(v.curve) || v.curve.length>10000
 || !v.summary || !Number.isSafeInteger(v.summary.closed) || v.summary.closed<0) throw Error('HTDY_SNAPSHOT_INVALID')
 for(const a of v.actions) if(!a.action_id || !a.reference_trade_id || !a.signal_id || !a.physical_contract || !a.segment_id || !a.calculation_segment_id || !instant(a.bar_end) || Date.parse(a.bar_end)>Date.parse(v.computed_through) || !decimal(a.reference_price) || Number(a.reference_price)<=0 || !['BUILD','CLEAR'].includes(a.role) || !['LONG','SHORT'].includes(a.side) || a.recording_mode!=='historical_replay') throw Error('HTDY_SNAPSHOT_INVALID')
 for(const t of v.trades) if(!t.reference_trade_id || !instant(t.entry_bar_end) || !decimal(t.entry_reference_price) || t.reference_return!==null && !decimal(t.reference_return)) throw Error('HTDY_SNAPSHOT_INVALID')
 for(const p of v.curve) if(!instant(p.bar_end) || !decimal(p.value) || !p.reference_trade_id) throw Error('HTDY_SNAPSHOT_INVALID')
 return v
}
