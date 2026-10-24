import type { HistoricalChartAction } from '../types/historicalChartAction'
import { withReferenceRead } from './referenceReadAdmission'
import request from './request'
import type { HistoricalSignalRangePage, HistoricalSignalRangeRequest } from '../composables/useHistoricalSignalRanges'
interface HistoricalSignalsWire {
  schema_version: string; symbol: string; strategy: string; frequency: string; recording_mode: 'historical_replay'; from: string; to: string
  identity: { stream_id: string; formula_versions: string[]; reference_model_version: string; input_snapshot_hash: string }
  coverage: { status: string; bar_count: number; completed_through?: string | null }
  items: HistoricalChartAction[]; next_cursor: string | null
}
export async function getHistoricalSignalRange(query: HistoricalSignalRangeRequest, signal: AbortSignal): Promise<HistoricalSignalRangePage> {
  const page = await withReferenceRead(() => request.get<never, HistoricalSignalsWire>(`/market/${encodeURIComponent(query.symbol)}/reference-signals`, { params: { strategy: query.strategy, frequency: query.frequency, since: query.since, through: query.through, from: query.from, to: query.to, cursor: query.before, limit: 200 }, signal }), signal)
  if (page.schema_version !== 'historical_signal_window_v2' || !page.identity || !Array.isArray(page.identity.formula_versions) || !page.identity.formula_versions.every(version => typeof version === 'string' && version.length > 0) || !/^[a-f0-9]{64}$/.test(page.identity.input_snapshot_hash) || !page.coverage || !['COMPLETE', 'PARTIAL_CANONICAL'].includes(page.coverage.status) || !Number.isInteger(page.coverage.bar_count) || page.coverage.bar_count < 0 || page.coverage.bar_count > 2000 || page.next_cursor !== null && typeof page.next_cursor !== 'string') throw new Error('HISTORICAL_SIGNAL_SCHEMA')
  if (page.symbol !== query.symbol || page.recording_mode !== 'historical_replay' || page.strategy !== query.strategy || page.frequency !== query.frequency || Date.parse(page.from) !== Date.parse(query.from) || Date.parse(page.to) !== Date.parse(query.to) || !Array.isArray(page.items) || page.items.length > 200) throw new Error('HISTORICAL_SIGNAL_IDENTITY')
  const decimal = /^-?\d+(?:\.\d+)?$/
  const seen = new Set<string>()
  for (const item of page.items) {
    if (!item || !['BUILD', 'CLEAR'].includes(item.role) || !['LONG', 'SHORT'].includes(item.side)
      || !['OPEN', 'CLOSED', 'ROLLOVER_INTERRUPTED', 'DATA_INTERRUPTED'].includes(item.status)
      || item.recording_mode !== 'historical_replay'
      || [item.action_id, item.reference_trade_id, item.signal_id, item.physical_contract, item.segment_id, item.calculation_segment_id].some(value => typeof value !== 'string' || !value)
      || !/^\d{4}-\d{2}-\d{2}$/.test(item.trading_day) || item.trading_day < query.since || item.trading_day > query.through
      || seen.has(item.action_id) || !Number.isFinite(Date.parse(item.bar_end))
      || Date.parse(item.bar_end) < Date.parse(query.from) || Date.parse(item.bar_end) > Date.parse(query.to)
      || typeof item.reference_price !== 'string' || !/^\d+(?:\.\d+)?$/.test(item.reference_price) || !/[1-9]/.test(item.reference_price)
      || item.return_pct !== null && (typeof item.return_pct !== 'string' || !decimal.test(item.return_pct) || item.role !== 'CLEAR' || item.status !== 'CLOSED')
      || item.role === 'CLEAR' && item.status !== 'CLOSED') throw new Error('HISTORICAL_ACTION_INVALID')
    seen.add(item.action_id)
  }
  return {
    identity: { symbol: query.symbol, strategy: page.strategy, frequency: page.frequency }, since: query.since, through: query.through, from: query.from, to: query.to,
    coverage: { status: page.coverage.status, completedThrough: page.coverage.completed_through },
    sourceToken: JSON.stringify(page.identity), nextCursor: page.next_cursor,
    signals: [], actions: page.items,
  }
}
