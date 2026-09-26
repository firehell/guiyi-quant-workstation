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
  const trades = value.items.filter(t => t.status === 'CLOSED' && t.statistics_membership === value.summary.membership_policy)
    .sort((a, b) => (a.exit_bar_end ?? '').localeCompare(b.exit_bar_end ?? '') || a.reference_trade_id.localeCompare(b.reference_trade_id))
  const pending = value.next_before !== null || trades.length !== value.summary.closed_count
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
  if (sum !== total.units * 10n ** BigInt(scale - total.scale) || points.some(p => !Number.isFinite(p.value))) {
    return { points: [], message: '逐笔累计与服务端摘要不一致，暂不绘制曲线。' }
  }
  return { points, message: null }
}
export type ReferenceCurvePoint = { trade: NewowReferenceTrade; cumulative: string; value: number }
