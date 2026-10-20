import type { FuturesSnapshot, FrozenRecord } from '../types/newowFutures.ts'
import type { MarketDetailIdentity } from '../types/marketDetail.ts'
import type { BarData, KlineMarker } from '../types/market.ts'
import type { KlineReferenceCallout, KlineReferenceIndicator } from '../types/referenceCallout.ts'
import { futuresAction, futuresStateLabel, futuresNumber, futuresTime } from './newowFuturesPresentation.ts'
import { futuresVariant } from './newowFutures.ts'
const instant = (value: unknown): value is string => typeof value === 'string' && /(?:Z|[+-]\d\d:\d\d)$/.test(value) && Number.isFinite(Date.parse(value))
const decimal = (value: unknown): value is string => typeof value === 'string' && /^-?\d+(?:\.\d+)?$/.test(value) && Number.isFinite(Number(value))
export function validateFuturesSnapshot(packet: FuturesSnapshot, identity: MarketDetailIdentity): FuturesSnapshot {
  const meta = packet?.metadata
  const nullableHash = ['DATA_INSUFFICIENT','EXECUTION_FACTS_MISSING','DATA_INTERRUPTED','NOT_APPLICABLE'].includes(meta?.status)
  const validHash = (value: unknown) => typeof value === 'string' && /^[a-f0-9]{64}$/.test(value) || (value === null && nullableHash)
  if (packet?.schema_version !== 1 || !meta || meta.auto_order !== false || meta.source !== 'historical_replay' || identity.strategyModel !== 'futures_bidir_v1' || meta.strategy_model !== identity.strategyModel
    || meta.strategy !== futuresVariant(identity) || meta.product?.toLowerCase() !== identity.symbol || meta.frequency !== identity.frequency
    || meta.scenario !== 'baseline' || !meta.run_id || packet.run_id !== meta.run_id || !/^[a-f0-9]{64}$/.test(packet.sha256)
    || !instant(meta.as_of) || !validHash(meta.input_snapshot_hash) || !validHash(meta.execution_facts_hash) || meta.profile_id !== `newow_futures_${futuresVariant(identity)}_${identity.frequency}_100k_v1`
    || !packet.summary || !packet.reference || !packet.chart || !Array.isArray(packet.chart.bars) || packet.chart.bars.length > 2000
    || !Array.isArray(packet.chart.frames) || !Array.isArray(packet.reference.actions) || !Array.isArray(packet.reference.trades)) throw new Error('RESULT_IDENTITY_MISMATCH')
  let previous = -Infinity
  for (const bar of packet.chart.bars) {
    const time = instant(bar.bar_end) ? Date.parse(bar.bar_end) : NaN
    if (!Number.isFinite(time) || time > Date.parse(meta.as_of) || time <= previous || !bar.physical_contract || !bar.owner_segment_id
      || !['open','high','low','close'].every(key => decimal(bar[key])) || !(decimal(bar.volume) || (typeof bar.volume === 'number' && Number.isFinite(bar.volume)))) throw new Error('RESULT_CHART_INVALID')
    previous = time
  }
  for (const action of packet.reference.actions) {
    if (action.display_bar_end !== undefined && !actionDisplayBar(packet, action)) throw new Error('RESULT_ACTION_COORDINATE_INVALID')
  }
  return packet
}
export function futuresChartBars(packet: FuturesSnapshot): BarData[] {
  return packet.chart.bars.map(bar => ({ time: String(bar.bar_end), physicalContract: String(bar.physical_contract),
    calculationSegmentId: String(bar.owner_segment_id), open: Number(bar.open), high: Number(bar.high), low: Number(bar.low), close: Number(bar.close), volume: Number(bar.volume) }))
}
/** Only server-proven display coordinates may move an action onto an enclosing chart bar. */
function actionDisplayBar(packet: FuturesSnapshot, action: FrozenRecord): FrozenRecord | null {
  const sourceTime = action.bar_end ?? action.at
  const displayTime = action.display_bar_end ?? sourceTime
  if (!instant(sourceTime) || !instant(displayTime) || (action.display_bar_end !== undefined && !action.physical_contract)) return null
  const index = packet.chart.bars.findIndex(bar => bar.bar_end === displayTime)
  const bar = packet.chart.bars[index]
  if (!bar || (action.physical_contract && action.physical_contract !== bar.physical_contract)
    || (action.owner_segment_id && action.owner_segment_id !== bar.owner_segment_id)) return null
  const sources = [action.at, action.bar_end].filter(value => value !== undefined)
  if (!sources.length || sources.some(value => !instant(value) || Date.parse(value) > Date.parse(displayTime))) return null
  if (sources.every(value => Date.parse(String(value)) === Date.parse(displayTime))) return bar
  // An off-chart source has no valid coordinate until the API supplies an explicit annotation.
  if (action.display_bar_end === undefined || !action.physical_contract) return null
  const previous = packet.chart.bars[index - 1]
  if (!previous || previous.physical_contract !== bar.physical_contract || previous.owner_segment_id !== bar.owner_segment_id
    || sources.some(value => Date.parse(String(value)) <= Date.parse(String(previous.bar_end)))) return null
  return bar
}
/** Display adapters only: no browser strategy, position or return calculation. */
export function futuresChartMarkers(packet: FuturesSnapshot): KlineMarker[] {
  return packet.reference.actions.flatMap((action, index) => {
    const bar = actionDisplayBar(packet, action)
    if (!bar) return []
    const time = bar.bar_end
    const sourceTime = action.at ?? action.bar_end
    const displaced = Date.parse(String(sourceTime)) !== Date.parse(String(time))
    const actualTimeLabel = displaced ? ` · 实际 ${futuresTime(sourceTime)}` : ''
    const side = action.side
    const exit = ['CLOSE','REDUCE'].includes(String(action.action ?? action.kind ?? action.type))
    const above = side === 'SHORT' ? !exit : exit
    return [{ id: String(action.id ?? action.action_id ?? `${packet.run_id}:${index}`), time: String(time),
      position: above ? 'aboveBar' as const : 'belowBar' as const, tone: side === 'SHORT' ? 'down' as const : 'up' as const,
      shape: 'circle' as const, label: `${futuresAction(action.action ?? action.kind ?? action.type)} ${futuresStateLabel(side)}${actualTimeLabel}`, tooltip: `参考价 ${futuresNumber(action.reference_price ?? action.price)} · 实际时间 ${futuresTime(sourceTime)}${displaced ? ` · 图表归属 ${futuresTime(time)}` : ''}`,
      physicalContract: String(bar.physical_contract), calculationSegmentId: String(bar.owner_segment_id) }]
  })
}
export function futuresChartCallouts(packet: FuturesSnapshot): KlineReferenceCallout[] {
  return futuresChartMarkers(packet).flatMap(marker => {
    const action = packet.reference.actions.find(item => String(item.action_id ?? item.id) === marker.id)
    const bar = packet.chart.bars.find(item => item.bar_end === marker.time)
    const price = action?.reference_price ?? action?.price
    if (!bar || typeof price !== 'string' || !Number.isFinite(Number(price))) return []
    return [{ id: marker.id, time: marker.time, physicalContract: String(bar.physical_contract), price, title: marker.label, detail: futuresNumber(price), tone: marker.tone === 'down' ? 'loss' as const : 'gain' as const, above: marker.position === 'aboveBar' }]
  })
}
export function frozenText(value: unknown): string {
  if (value === null || value === undefined) return '不可用'
  if (Array.isArray(value)) return value.length ? value.map(frozenText).join(' · ') : '无'
  if (typeof value === 'object') return Object.entries(value as FrozenRecord).map(([key,val])=>`${key}: ${frozenText(val)}`).join(' · ')
  return String(value)
}
export function futuresErrorCode(error: unknown): string {
  if (error instanceof Error && /^RESULT_[A-Z_]+$/.test(error.message)) return error.message
  const data = (error as { response?: { data?: { detail?: unknown; code?: unknown } } })?.response?.data
  const detail = data?.detail
  const code = typeof detail === 'string' ? detail : typeof detail === 'object' && detail !== null ? (detail as { code?: unknown }).code : data?.code
  return typeof code === 'string' && ['RESULT_NOT_FOUND','RESEARCH_NOT_COVERED','RESULT_INTEGRITY_FAILED','RESULT_SCHEMA_INVALID','RESULT_IDENTITY_MISMATCH'].includes(code) ? code : '研究结果不可用'
}
export function createFuturesSnapshotResource(fetch: (identity: MarketDetailIdentity, signal: AbortSignal) => Promise<FuturesSnapshot>, update: (packet: FuturesSnapshot | null, loading: boolean, error: string | null) => void) {
  let owner: AbortController | null = null
  return {
    async load(identity: MarketDetailIdentity) {
      owner?.abort(); const current = owner = new AbortController()
      if (!['jm','rb','al','ta'].includes(identity.symbol)) { update(null, false, 'RESEARCH_NOT_COVERED'); return }
      update(null, true, null)
      try { const packet = validateFuturesSnapshot(await fetch(identity, current.signal), identity); if (!current.signal.aborted) update(packet, false, null) }
      catch (error) { if (!current.signal.aborted) update(null, false, futuresErrorCode(error)) }
    },
    dispose() { owner?.abort() },
  }
}

/** Frame prices remain server facts; no target/stop or strategy is computed here. */
export function futuresReferenceIndicators(packet: FuturesSnapshot, target: boolean, stop: boolean): KlineReferenceIndicator[] {
  return packet.chart.bars.flatMap(bar => {
    const frame = packet.chart.frames.find(frame => (frame.bar_end ?? frame.at) === bar.bar_end)
    if (!frame || !['LONG','SHORT'].includes(String(frame.side))
      || (frame.physical_contract && frame.physical_contract !== bar.physical_contract)
      || (frame.owner_segment_id && frame.owner_segment_id !== bar.owner_segment_id)) return []
    return [{ bar_end: String(bar.bar_end), physical_contract: String(bar.physical_contract), segment_id: String(bar.owner_segment_id), owner_segment_id: String(bar.owner_segment_id),
      reference_side: frame.side as 'LONG' | 'SHORT', dif: null, dea: null, macd: null, ema21: null,
      target_reference_price: target && typeof frame.target_reference_price === 'string' ? frame.target_reference_price : null,
      stop_reference_price: stop && typeof frame.stop_reference_price === 'string' ? frame.stop_reference_price : null }]
  })
}
