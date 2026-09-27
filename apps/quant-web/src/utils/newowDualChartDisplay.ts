import type { NewowProductChartModel } from '../components/market/detail/newow/newowProductChartPrimitives.ts'
import type { NewowReferenceTrade } from '../types/newowProduct.ts'
import { layoutNiuwaReferenceCallouts, type ProjectedCallout } from './referenceCalloutLayout.ts'

export type DualOrigin = 'trend' | 'oscillation'
export interface DualPoint extends ProjectedCallout { origin: DualOrigin }

/** Same stable record may appear in both the curve and page; conflicting records are unusable. */
export function mergeNewowDualReferences(trades: readonly NewowReferenceTrade[]) {
  const accepted = new Map<string, NewowReferenceTrade>()
  const conflicts = new Set<string>()
  const fingerprint = (trade: NewowReferenceTrade) => JSON.stringify(Object.entries(trade).sort(([a], [b]) => a.localeCompare(b)))
  for (const trade of trades) {
    if (!trade.reference_trade_id) continue
    const key = `${trade.strategy_code}:${trade.reference_trade_id}`
    if (conflicts.has(key)) continue
    const previous = accepted.get(key)
    if (previous && fingerprint(previous) !== fingerprint(trade)) {
      accepted.delete(key); conflicts.add(key)
    } else if (!previous) accepted.set(key, trade)
  }
  return [...accepted.values()]
}

/** Price anchors remain real; only the text boxes are constrained to two regions. */
export function layoutNewowDualCallouts(points: readonly DualPoint[], width: number, height: number) {
  const middle = (height + 20) / 2
  return (['trend', 'oscillation'] as const).flatMap(origin => {
    const top = origin === 'trend' ? 20 : middle
    const bottom = origin === 'trend' ? middle : height - 2
    const source = points.filter(p => p.origin === origin && p.x >= 0 && p.x <= width)
    const anchors = new Map(source.map(p => [p.callout.id, p]))
    return layoutNiuwaReferenceCallouts(source.map(p => ({ ...p,
      y: Math.min(bottom - top - 2, Math.max(2, p.y - top)),
      candle: p.candle ? { ...p.candle, top: p.candle.top - top } : undefined,
    })), width, bottom - top).map(p => ({ ...p, origin,
      top: p.top + top, lineY: p.lineY + top, y: anchors.get(p.callout.id)!.y,
    }))
  })
}

/** Public display-only dominance rule. Reset at each physical/calculation owner. */
export function newowDualDominance(base: NewowProductChartModel, models: readonly NewowProductChartModel[]) {
  let dominant: DualOrigin | null = null
  let owner = ''
  let lastDrawn = -Infinity
  const switches: Array<{ index: number; from: DualOrigin; to: DualOrigin }> = []
  const byTime = new Map<string, Array<{ origin: DualOrigin; kind: 'BUILD' | 'CLEAR' }>>()
  for (const model of models) for (const action of model.actions) {
    const bar = base.bars.find(b => b.barEnd === action.barEnd && b.physicalContract === action.physicalContract && b.segmentId === action.segmentId)
    if (!bar || !['trend', 'oscillation'].includes(model.identity.strategy)) continue
    const list = byTime.get(action.barEnd) ?? []
    list.push({ origin: model.identity.strategy as DualOrigin, kind: action.kind }); byTime.set(action.barEnd, list)
  }
  base.bars.forEach((bar, index) => {
    const nextOwner = `${bar.physicalContract}:${bar.calculationSegmentId}`
    if (owner !== nextOwner) { dominant = null; lastDrawn = -Infinity; owner = nextOwner }
    const actions = byTime.get(bar.barEnd) ?? []
    const any = (['trend', 'oscillation'] as const).filter(s => actions.some(a => a.origin === s))
    const buys = any.filter(s => actions.some(a => a.origin === s && a.kind === 'BUILD'))
    const next = buys.length === 1 ? buys[0]! : buys.length > 1 ? dominant ?? any[0]! : any.length === 1 ? any[0]! : dominant ?? any[0] ?? null
    if (dominant && next && dominant !== next && index - lastDrawn >= 12) {
      switches.push({ index, from: dominant, to: next }); lastDrawn = index
    }
    dominant = next
  })
  return { dominant, switches }
}

/** Summarize exact CLOSED reference records represented by the visible labels. */
export function newowDualVisibleStatistics(points: readonly DualPoint[], trades: readonly NewowReferenceTrade[]) {
  const returns = points.flatMap(p => {
    if (!p.callout.above) return []
    const matches = trades.filter(t => t.status === 'CLOSED' && t.strategy_code === p.origin
      && t.exit_signal_id === p.callout.id && t.exit_bar_end === p.callout.time
      && t.physical_contract === p.callout.physicalContract && t.exit_reference_price === p.callout.price)
    const value = matches.length === 1 ? matches[0]!.reference_return_pct : null
    return value != null && /^-?\d+(\.\d+)?$/.test(value) ? [value] : []
  })
  if (!returns.length) return { count: points.length, samples: 0, average: '—', winRate: '—', maximum: '—' }
  const scale = Math.max(...returns.map(v => v.split('.')[1]?.length ?? 0))
  const unit = 10n ** BigInt(scale)
  const values = returns.map(v => {
    const [whole, fraction = ''] = v.replace('-', '').split('.')
    return BigInt(whole! + fraction.padEnd(scale, '0')) * (v.startsWith('-') ? -1n : 1n)
  })
  function percent(numerator: bigint, denominator = unit): string {
    const negative = numerator < 0n
    const magnitude = negative ? -numerator : numerator
    const tenths = (magnitude * 10n + denominator / 2n) / denominator
    return `${negative && tenths !== 0n ? '-' : '+'}${tenths / 10n}.${tenths % 10n}%`
  }
  return { count: points.length, samples: values.length,
    average: percent(values.reduce((a, b) => a + b, 0n), unit * BigInt(values.length)),
    winRate: `${Math.round(values.filter(v => v > 0n).length / values.length * 100)}%`,
    maximum: percent(values.reduce((a, b) => a > b ? a : b)),
  }
}
