import type { NewowReferenceValue, NewowReferenceTrade } from '../types/newowProduct.ts'

// Decimal addition remains exact; Number is used only for SVG coordinates.
function decimal(value: string): { units: bigint; scale: number } | null {
  if (!/^-?\d+(\.\d+)?$/.test(value)) return null
  const [whole, fraction = ''] = value.split('.')
  return { units: BigInt(whole! + fraction), scale: fraction.length }
}
function text(units: bigint, scale: number): string {
  const digits = (units < 0n ? -units : units).toString().padStart(scale + 1, '0')
  return `${units < 0n ? '-' : ''}${scale ? `${digits.slice(0, -scale)}.${digits.slice(-scale)}` : digits}`
}
export function newowReferenceCurve(value: NewowReferenceValue) {
  const source = value.curve_trades ?? value.items
  const trades = source.filter(t => t.status === 'CLOSED' && t.statistics_membership === value.summary.membership_policy)
    .sort((a, b) => (a.exit_bar_end ?? '').localeCompare(b.exit_bar_end ?? '') || a.reference_trade_id.localeCompare(b.reference_trade_id))
  const pending = (value.curve_trades === undefined && value.next_before !== null) || trades.length !== value.summary.closed_count
  if (pending) return { points: [], message: '参考历史尚未完整加载；加载更多后显示完整累计曲线。' }
  if (!trades.length) return { points: [], message: '暂无已完成参考交易；未清仓与中断结果不计入曲线。' }
  const numbers = trades.map(t => t.reference_return_pct === null ? null : decimal(t.reference_return_pct))
  const total = value.summary.sum_return_percentage_points === null ? null : decimal(value.summary.sum_return_percentage_points)
  if (numbers.some(n => n === null) || total === null || trades.some(t => t.exit_bar_end === null)
    || new Set(trades.map(t => t.reference_trade_id)).size !== trades.length) return { points: [], message: '参考收益事实不完整，暂不绘制累计曲线。' }
  const scale = Math.max(total.scale, ...numbers.map(n => n!.scale))
  let sum = 0n
  const points = trades.map((trade, index) => {
    sum += numbers[index]!.units * 10n ** BigInt(scale - numbers[index]!.scale)
    return { trade, cumulative: text(sum, scale), value: Number(text(sum, scale)) }
  })
  // The authoritative summary adds in Decimal(precision=28, HALF_EVEN).
  // Bound the cumulative rounding error in integer units; never compare floats.
  const magnitudeDigits = Math.max(1, ...points.map(p => (p.cumulative.replace('-', '').split('.')[0] ?? '').length),
    ...trades.map(t => (t.reference_return_pct!.replace('-', '').split('.')[0] ?? '').length))
  const roundingUnit = scale + magnitudeDigits > 28 ? 10n ** BigInt(scale + magnitudeDigits - 28) : 0n
  const expected = total.units * 10n ** BigInt(scale - total.scale)
  const difference = sum > expected ? sum - expected : expected - sum
  if (difference > roundingUnit * BigInt(trades.length) || points.some(p => !Number.isFinite(p.value))) {
    return { points: [], message: '逐笔累计与服务端摘要不一致，暂不绘制曲线。' }
  }
  return { points, message: null }
}
export type ReferenceCurvePoint = { trade: NewowReferenceTrade; cumulative: string; value: number }

/** Display-only page reference annualization; the additive trade curve remains unchanged. */
export function newowReferenceAnnualized(value: NewowReferenceValue): number | null {
  const curve = newowReferenceCurve(value)
  if (value.history_coverage !== 'FULL' || curve.message !== null || !curve.points.length) return null
  const start = Date.parse(value.performance_since)
  const end = Date.parse(value.performance_through < value.actual_available_through ? value.performance_through : value.actual_available_through)
  const days = (end - start) / 86_400_000
  const ratio = 1 + curve.points.at(-1)!.value / 100
  if (!Number.isFinite(days) || days <= 0 || ratio <= 0) return null
  const annual = (Math.pow(ratio, 365 / days) - 1) * 100
  return Number.isFinite(annual) ? annual : null
}

export function newowTheoreticalDisplay(value: NewowReferenceValue): NewowReferenceValue | null {
  const theory = value.theoretical
  const source = value.curve_trades ?? value.items
  const closed = source.filter(trade => trade.status === 'CLOSED' && trade.statistics_membership === value.summary.membership_policy)
  if (!theory || theory.model_version !== 'newow_hindsight_peak_reference_v1' || theory.hindsight !== true || theory.executable !== false || closed.length !== value.summary.closed_count) return null
  const returns = new Map(theory.returns.map(item => [item.reference_trade_id, item.return_pct]))
  if (returns.size !== closed.length || theory.returns.length !== closed.length || closed.some(trade => !returns.has(trade.reference_trade_id))) return null
  return { ...value, curve_trades: closed.map(trade => ({ ...trade, reference_return_pct: returns.get(trade.reference_trade_id)! })), summary: { ...value.summary, sum_return_percentage_points: theory.sum_return_percentage_points, win_rate_pct: theory.win_rate_pct, mean_return_pct: theory.mean_return_pct } }
}

/** Page curve only: peak-to-trough loss of 100 + additive return, including starting capital 100. */
export function newowReferenceDrawdown(value: NewowReferenceValue): string | null {
  const curve = newowReferenceCurve(value)
  if (value.history_coverage !== 'FULL' || curve.message !== null || !curve.points.length) return null
  const values = curve.points.map(point => decimal(point.cumulative)!)
  const scale = Math.max(...values.map(item => item.scale))
  const baseline = 100n * 10n ** BigInt(scale)
  let peak = baseline
  let numerator = 0n
  let denominator = baseline
  for (const item of values) {
    const equity = baseline + item.units * 10n ** BigInt(scale - item.scale)
    if (equity > peak) peak = equity
    const loss = peak - equity
    if (loss * denominator > numerator * peak) { numerator = loss; denominator = peak }
  }
  // Round percentage to two decimal places without binary floating-point arithmetic.
  const scaled = numerator * 10000n
  const rounded = scaled / denominator + (scaled % denominator * 2n >= denominator ? 1n : 0n)
  return text(rounded, 2)
}
