import type { SubingReferenceResponse, SubingReferenceSignal } from '../types/subingReference.ts'

import type { KlineReferenceCallout } from '../types/referenceCallout.ts'
import { formatDecimalText, formatMarketDecimal } from './marketDisplay.ts'

const decimal = /^-?\d+(?:\.\d+)?$/
const day = /^\d{4}-\d{2}-\d{2}$/
function record(value: unknown): Record<string, unknown> { if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('历史参考响应无效'); return value as Record<string, unknown> }
function requireThat(condition: unknown): asserts condition { if (!condition) throw new Error('历史参考身份或字段无效') }
const isText = (value: unknown) => typeof value === 'string' && value.length > 0
const isTime = (value: unknown) => typeof value === 'string' && /(?:Z|[+-]\d{2}:\d{2})$/.test(value) && Number.isFinite(Date.parse(value))
const isMoney = (value: unknown) => typeof value === 'string' && value.length < 100 && decimal.test(value)
export function normalizeSubingReference(value: unknown, symbol: string): SubingReferenceResponse {
  const root = record(value)
  const versions: Record<string, string> = { '15m': 'subing_ths_15m_v3', '30m': 'subing_ths_30m_v1', '60m': 'subing_ths_60m_v1', '1d': 'subing_ths_1d_v1' }
  requireThat(root.symbol === symbol.toLowerCase() && typeof root.frequency === 'string' && versions[root.frequency] === root.formula_version && root.series_kind === 'actual_dominant' && root.reference_model_version === 'subing_reference_reverse_close_v1' && root.executable === false && root.auto_order === false && root.source === 'historical_replay' && ['ready', 'warming'].includes(root.research_status as string))
  requireThat(isTime(root.as_of) && isTime(root.reference_cutoff) && typeof root.performance_since === 'string' && day.test(root.performance_since) && typeof root.performance_through === 'string' && day.test(root.performance_through) && root.performance_since <= root.performance_through && typeof root.input_snapshot_hash === 'string' && /^[a-f0-9]{64}$/.test(root.input_snapshot_hash))
  const summary = record(root.summary)
  for (const key of ['closed_count', 'win_count', 'loss_count', 'flat_count', 'open_count', 'interrupted_count', 'initial_count']) requireThat(Number.isSafeInteger(summary[key]) && (summary[key] as number) >= 0)
  for (const key of ['win_rate_pct', 'mean_return_pct']) requireThat(summary[key] === null || isMoney(summary[key]))
  requireThat(isMoney(summary.sum_return_percentage_points))
  requireThat(Array.isArray(root.signals) && Array.isArray(root.indicators) && Array.isArray(root.items) && (root.next_before === null || isText(root.next_before)))
  for (const raw of root.indicators) {
    const point = record(raw)
    requireThat(isTime(point.bar_end) && isText(point.physical_contract) && isText(point.segment_id))
    for (const key of ['dif', 'dea', 'macd', 'ema21']) requireThat(point[key] === null || isMoney(point[key]))
  }
  const ids = new Set<string>()
  for (const raw of root.signals) {
    const signal = record(raw)
    requireThat(isText(signal.signal_id) && !ids.has(signal.signal_id as string)); ids.add(signal.signal_id as string)
    requireThat(isTime(signal.bar_end) && typeof signal.trading_day === 'string' && day.test(signal.trading_day) && isText(signal.physical_contract) && isText(signal.segment_id) && isMoney(signal.reference_price) && ['buy', 'sell'].includes(signal.direction as string) && ['OPEN_LONG', 'OPEN_SHORT', 'REVERSE_TO_LONG', 'REVERSE_TO_SHORT', 'SAME_DIRECTION'].includes(signal.action as string))
    requireThat(signal.action === 'SAME_DIRECTION' || (signal.direction === 'buy' ? ['OPEN_LONG', 'REVERSE_TO_LONG'] : ['OPEN_SHORT', 'REVERSE_TO_SHORT']).includes(signal.action as string))
    for (const key of ['entry_trade_id', 'closed_trade_id']) requireThat(signal[key] === null || isText(signal[key]))
    requireThat(signal.closed_return_pct === null || isMoney(signal.closed_return_pct))
    for (const key of ['dif', 'dea', 'macd', 'ema21']) requireThat(signal[key] === undefined || signal[key] === null || isMoney(signal[key]))
  }
  ids.clear()
  for (const raw of root.items) {
    const trade = record(raw)
    requireThat(isText(trade.reference_trade_id) && !ids.has(trade.reference_trade_id as string)); ids.add(trade.reference_trade_id as string)
    for (const key of ['physical_contract', 'segment_id', 'entry_signal_id']) requireThat(isText(trade[key]))
    requireThat(['LONG', 'SHORT'].includes(trade.side as string) && ['OPEN', 'CLOSED', 'ROLLOVER_INTERRUPTED'].includes(trade.status as string) && isTime(trade.entry_bar_end) && isMoney(trade.entry_reference_price) && Number.isSafeInteger(trade.holding_bars) && (trade.holding_bars as number) >= 0 && typeof trade.initial === 'boolean')
    for (const key of ['exit_reference_price', 'reference_return_pct', 'mark_reference_price', 'mark_change_pct']) requireThat(trade[key] === null || isMoney(trade[key]))
    for (const key of ['exit_bar_end', 'mark_bar_end', 'interrupted_at']) requireThat(trade[key] === null || isTime(trade[key]))
    requireThat(typeof trade.entry_trading_day === 'string' && day.test(trade.entry_trading_day) && (trade.exit_trading_day === null || typeof trade.exit_trading_day === 'string' && day.test(trade.exit_trading_day)) && (trade.exit_signal_id === null || isText(trade.exit_signal_id)))
    requireThat(trade.status === 'CLOSED' || (trade.exit_signal_id === null && trade.exit_bar_end === null && trade.exit_reference_price === null && trade.reference_return_pct === null))
    requireThat(trade.status !== 'CLOSED' || (trade.exit_signal_id !== null && trade.exit_bar_end !== null && trade.exit_reference_price !== null && trade.reference_return_pct !== null))
  }
  return value as SubingReferenceResponse
}
export const subingActionLabel = (action: SubingReferenceSignal['action']) => ({ OPEN_LONG: '建仓', OPEN_SHORT: '建仓', REVERSE_TO_LONG: '平空·开多', REVERSE_TO_SHORT: '平多·开空', SAME_DIRECTION: '同向·不加仓' })[action]
export function referenceTone(value: string | null): 'gain' | 'loss' | 'neutral' { return value === null || /^-?0(?:\.0+)?$/.test(value) ? 'neutral' : value.startsWith('-') ? 'loss' : 'gain' }
export function subingCallouts(signals: SubingReferenceSignal[]): KlineReferenceCallout[] { return signals.map((signal) => ({ id: signal.signal_id, time: signal.bar_end, physicalContract: signal.physical_contract, price: signal.reference_price, title: subingActionLabel(signal.action), detail: signal.closed_return_pct !== null ? `${formatMarketDecimal(signal.reference_price)} (${referenceDecimalDisplay(signal.closed_return_pct)}%)` : signal.action === 'SAME_DIRECTION' ? formatMarketDecimal(signal.reference_price) : `建仓价: ${formatMarketDecimal(signal.reference_price)}`, tone: referenceTone(signal.closed_return_pct), above: signal.direction === 'sell' })) }
/** Display rounding of a server Decimal only; never recomputes performance. */
export function referenceDecimalDisplay(value: string | null, signed = true): string {
  return formatDecimalText(value, { maximumFractionDigits: 2, minimumFractionDigits: 2, signed })
}
