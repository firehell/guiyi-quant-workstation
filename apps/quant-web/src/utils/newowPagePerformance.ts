export interface PageEstimateTrade {
  readonly buyDate: string; readonly buyPrice: string; readonly sellDate: string; readonly sellPrice: string
  readonly pct: string; readonly forceClose: boolean; readonly buyBarIsLive?: boolean; readonly segment_id: string
}
export interface PagePerformanceMode {
  readonly period: string
  readonly summary: { readonly cumReturn: string; readonly accuracy: number; readonly maxDrawdown: string; readonly tradeCount: number }
  readonly dates: readonly string[]; readonly trading_days: readonly string[]; readonly segment_ids: readonly string[]
  readonly equity: readonly string[]; readonly trades: readonly PageEstimateTrade[]
}
export interface PagePerformance {
  readonly version: 'newow_page_performance_v3379_v1'; readonly source_version: '3.3.79'; readonly source_sha256: string
  readonly page_parity: true; readonly executable: false; readonly strategy: 'trend' | 'oscillation' | 'main_rise' | 'fusion'
  readonly input_sha256: string; readonly source_evidence_sha256: string | null
  readonly segment_count: number; readonly ordinary_interrupted_count: number; readonly ideal_open_count: number
  readonly ordinary: PagePerformanceMode | null; readonly ideal: PagePerformanceMode | null
}
const sourceHash = '3c1d600a1bd59dc8d8edfe46dd0cdfa1b44dbd9e7124a20d509426eb1d66973d'
function obj(v: unknown): Record<string, unknown> { if (!v || typeof v !== 'object' || Array.isArray(v)) throw Error('page_performance object invalid'); return v as Record<string, unknown> }
function exact(v: Record<string, unknown>, fields: string[]) { if (Object.keys(v).some(k => !fields.includes(k)) || fields.some(k => !Object.hasOwn(v, k))) throw Error('page_performance fields invalid') }
function text(v: unknown): string { if (typeof v !== 'string' || !v) throw Error('page_performance text invalid'); return v }
function decimal(v: unknown): string { const s = text(v); if (!/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$/.test(s) || !Number.isFinite(Number(s))) throw Error('page_performance decimal invalid'); return s }
function count(v: unknown): number { if (!Number.isSafeInteger(v) || Number(v) < 0) throw Error('page_performance count invalid'); return Number(v) }
function list(v: unknown): unknown[] { if (!Array.isArray(v)) throw Error('page_performance list invalid'); return v }
function mode(v: unknown, cutoff?: string, ideal = false): PagePerformanceMode | null {
  if (v === null) return null
  const m = obj(v), s = obj(m.summary)
  exact(m, ['period','summary','dates','trading_days','segment_ids','equity','trades'])
  exact(s, ['cumReturn','accuracy','maxDrawdown','tradeCount'])
  const dates = list(m.dates).map(text), days = list(m.trading_days).map(text), segments = list(m.segment_ids).map(text), equity = list(m.equity).map(decimal)
  if ([days, segments, equity].some(items => items.length !== dates.length)) throw Error('page_performance curve dimensions invalid')
  if (dates.some(d => !Number.isFinite(Date.parse(d)) || (cutoff !== undefined && Date.parse(d) > Date.parse(cutoff)))) throw Error('page_performance future or invalid date')
  if (dates.some((d,i) => i > 0 && Date.parse(d) <= Date.parse(dates[i-1]!))) throw Error('page_performance curve order invalid')
  if (days.some(d => !/^\d{4}-\d{2}-\d{2}$/.test(d))) throw Error('page_performance day invalid')
  const completedSegments = new Set<string>()
  segments.forEach((segment, i) => {
    if (i > 0 && segment !== segments[i-1]) completedSegments.add(segments[i-1]!)
    if (completedSegments.has(segment)) throw Error('page_performance owner recurrence invalid')
  })

  const trades = list(m.trades).map(raw => {
    const t = obj(raw)
    exact(t, ['buyDate','buyPrice','sellDate','sellPrice','pct','forceClose','segment_id', ...(Object.hasOwn(t, 'buyBarIsLive') ? ['buyBarIsLive'] : [])])
    if (typeof t.forceClose !== 'boolean' || (t.buyBarIsLive !== undefined && typeof t.buyBarIsLive !== 'boolean')) throw Error('page_performance estimate flags invalid')
    if (ideal && t.forceClose || t.buyBarIsLive === true && !t.forceClose) throw Error('page_performance forceClose contradiction')
    const buyDate = text(t.buyDate), sellDate = text(t.sellDate)
    if (!Number.isFinite(Date.parse(buyDate)) || !Number.isFinite(Date.parse(sellDate)) || Date.parse(buyDate) > Date.parse(sellDate) || (cutoff !== undefined && Date.parse(sellDate) > Date.parse(cutoff))) throw Error('page_performance trade chronology invalid')
    const buyPrice = decimal(t.buyPrice), sellPrice = decimal(t.sellPrice)
    if (Number(buyPrice) <= 0 || Number(sellPrice) <= 0) throw Error('page_performance price invalid')
    const segment = text(t.segment_id), exit = dates.indexOf(sellDate), entry = dates.indexOf(buyDate)
    if (exit < 0 || segments[exit] !== segment || (entry >= 0 && segments[entry] !== segment)) throw Error('page_performance trade owner invalid')
    if (entry < 0 && Date.parse(buyDate) >= Date.parse(dates.find((_,i)=>segments[i] === segment)!)) throw Error('page_performance entry date invalid')
    if (t.forceClose && (exit !== dates.length-1 || segment !== segments.at(-1))) throw Error('page_performance terminal invalid')
    if (t.buyBarIsLive === true && buyDate !== sellDate) throw Error('page_performance terminal buy invalid')
    return { buyDate, buyPrice, sellDate, sellPrice, pct: decimal(t.pct), forceClose: t.forceClose, ...(t.buyBarIsLive === undefined ? {} : {buyBarIsLive: t.buyBarIsLive}), segment_id: segment }
  })
  const accuracy = count(s.accuracy), tradeCount = count(s.tradeCount)
  if (accuracy > 100 || tradeCount !== trades.length) throw Error('page_performance summary invalid')
  return {period: text(m.period), summary: {cumReturn: decimal(s.cumReturn), accuracy, maxDrawdown: decimal(s.maxDrawdown), tradeCount}, dates, trading_days: days, segment_ids: segments, equity, trades}
}
export function normalizePagePerformance(v: unknown, strategy: PagePerformance['strategy'], cutoff?: string, period?: string): PagePerformance | null {
  if (v === undefined || v === null) return null
  const p = obj(v)
  exact(p, ['version','source_version','source_sha256','page_parity','executable','strategy','segment_count','ordinary_interrupted_count','ideal_open_count','ordinary','ideal','input_sha256','source_evidence_sha256'])
  if (p.version !== 'newow_page_performance_v3379_v1' || p.source_version !== '3.3.79' || p.source_sha256 !== sourceHash || p.page_parity !== true || p.executable !== false || p.strategy !== strategy) throw Error('page_performance source identity invalid')
  const inputHash = text(p.input_sha256), evidenceHash = p.source_evidence_sha256 === null ? null : text(p.source_evidence_sha256)
  if (!/^[a-f0-9]{64}$/.test(inputHash) || evidenceHash !== null && !/^[a-f0-9]{64}$/.test(evidenceHash)) throw Error('page_performance input identity invalid')
  const ordinary = mode(p.ordinary, cutoff), ideal = mode(p.ideal, cutoff, true), segmentCount = count(p.segment_count)
  if (period !== undefined && [ordinary, ideal].some(m => m !== null && m.period !== period)) throw Error('page_performance period invalid')
  if (new Set([...(ordinary?.segment_ids ?? []), ...(ideal?.segment_ids ?? [])]).size > segmentCount) throw Error('page_performance owner count invalid')
  return {version: p.version, source_version: p.source_version, source_sha256: sourceHash, page_parity: true, executable: false, strategy, input_sha256: inputHash, source_evidence_sha256: evidenceHash, segment_count: segmentCount, ordinary_interrupted_count: count(p.ordinary_interrupted_count), ideal_open_count: count(p.ideal_open_count), ordinary, ideal}
}

export function pagePerformancePlot(mode: PagePerformanceMode | null) {
  if (!mode || mode.equity.length === 0) return []
  const values = mode.equity.map(Number), low = Math.min(0, ...values), high = Math.max(0, ...values)
  const span = high - low || 1
  const parts: string[] = []
  values.forEach((v, i) => {
    if (i === 0 || mode.segment_ids[i] !== mode.segment_ids[i - 1]) parts.push('')
    parts[parts.length - 1] += `${i / Math.max(1, values.length - 1) * 712},${140 - (v-low)/span*140} `
  })
  return parts
}
