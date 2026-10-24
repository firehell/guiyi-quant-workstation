import { withReferenceRead } from './referenceReadAdmission'
import request from './request'
import type { HistoricalSignalRangePage, HistoricalSignalRangeRequest } from '../composables/useHistoricalSignalRanges'
interface SignalWire { bar_end: string; trading_day: string; physical_contract: string; direction: 'buy' | 'sell'; reference_price: string | number }
interface HistoricalSignalsWire {
  schema_version: string; strategy: string; frequency: string; recording_mode: 'historical_replay'; from: string; to: string
  identity: { stream_id: string; formula_versions: string[]; reference_model_version: string; input_snapshot_hash: string }
  coverage: { status: string; bar_count: number; completed_through?: string | null }
  items: SignalWire[]; next_cursor: string | null
}
export async function getHistoricalSignalRange(query: HistoricalSignalRangeRequest, signal: AbortSignal): Promise<HistoricalSignalRangePage> {
  const page = await withReferenceRead(() => request.get<never, HistoricalSignalsWire>(`/market/${encodeURIComponent(query.symbol)}/reference-signals`, { params: { strategy: query.strategy, frequency: query.frequency, since: query.since, through: query.through, from: query.from, to: query.to, cursor: query.before, limit: 200 }, signal }), signal)
  if (page.schema_version !== 'historical_signal_window_v1' || !page.identity || !Array.isArray(page.identity.formula_versions) || !page.identity.formula_versions.every(version => typeof version === 'string' && version.length > 0) || !/^[a-f0-9]{64}$/.test(page.identity.input_snapshot_hash) || !page.coverage || !['COMPLETE', 'PARTIAL_CANONICAL'].includes(page.coverage.status) || !Number.isInteger(page.coverage.bar_count) || page.coverage.bar_count < 0 || page.coverage.bar_count > 2000 || page.next_cursor !== null && typeof page.next_cursor !== 'string') throw new Error('HISTORICAL_SIGNAL_SCHEMA')
  if (page.recording_mode !== 'historical_replay' || page.strategy !== query.strategy || page.frequency !== query.frequency || Date.parse(page.from) !== Date.parse(query.from) || Date.parse(page.to) !== Date.parse(query.to) || !Array.isArray(page.items) || page.items.length > 200) throw new Error('HISTORICAL_SIGNAL_IDENTITY')
  const version = [...page.identity.formula_versions].sort().join('|') || undefined
  return {
    identity: { symbol: query.symbol, strategy: page.strategy, frequency: page.frequency }, since: query.since, through: query.through, from: query.from, to: query.to,
    coverage: { status: page.coverage.status, completedThrough: page.coverage.completed_through },
    sourceToken: JSON.stringify(page.identity), nextCursor: page.next_cursor,
    signals: page.items.map(item => {
      const buy = item.direction === 'buy'
      if ((!buy && item.direction !== 'sell') || !item.physical_contract || !Number.isFinite(Date.parse(item.bar_end)) || Date.parse(item.bar_end) < Date.parse(query.from) || Date.parse(item.bar_end) > Date.parse(query.to) || typeof item.reference_price !== 'string' || !/^\d+(?:\.\d+)?$/.test(item.reference_price)) throw new Error('HISTORICAL_SIGNAL_INVALID')
      return { strategy: page.strategy, frequency: page.frequency, formulaVersion: version, barEnd: item.bar_end, physicalContract: item.physical_contract, source: 'historical_replay', marker: { id: `history:${page.strategy}:${item.physical_contract}:${item.bar_end}:${item.direction}`, time: item.bar_end, label: buy ? '买入参考' : '卖出参考', tooltip: `历史重算 · 参考价 ${item.reference_price}`, tone: page.strategy === 'htdy' ? 'htdy' : buy ? 'up' : 'down', position: buy ? 'belowBar' : 'aboveBar', shape: buy ? 'arrowUp' : 'arrowDown' } }
    }),
  }
}
