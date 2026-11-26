import type { BarData, KlineMarker } from '../types/market.ts'
import type { MarketAfterCloseFrame } from '../types/referenceTrading.ts'

const PRICE_LINES: Record<string, { label: string; color: string }> = {
  a: { label: '趋势 A', color: '#b48b16' }, b: { label: '趋势 B', color: '#5079b7' },
  upper: { label: '震荡上沿', color: '#b48b16' }, lower: { label: '震荡下沿', color: '#5079b7' },
  ma35: { label: 'MA35', color: '#b48b16' }, ma45: { label: 'MA45', color: '#5079b7' },
  ma10_display_v1: { label: 'MA10', color: '#8b58a6' },
}

export interface SavedReferenceLine {
  id: string
  label: string
  color: string
  sourceRevision: string | null
  formulaVersion: string | null
  points: { time: string; value: number }[]
}

export function projectMarketReferenceChart(
  frames: readonly MarketAfterCloseFrame[], bars: readonly BarData[],
  product: string, strategy: string, frequency: string, sourceRevision: string | null = null,
) {
  const byTime = new Map<number, MarketAfterCloseFrame>()
  const ambiguous = new Set<number>()
  for (const frame of frames) {
    if (frame.product !== product || frame.strategy !== strategy || frame.frequency !== frequency) continue
    const time = Date.parse(frame.bar_end)
    if (!Number.isFinite(time)) continue
    if (byTime.has(time)) ambiguous.add(time)
    else byTime.set(time, frame)
  }
  const markers: KlineMarker[] = []
  const lines = new Map<string, SavedReferenceLine>()
  const matched: MarketAfterCloseFrame[] = []
  let active = new Map<string, SavedReferenceLine>()
  let owner: string | undefined
  for (const bar of bars) {
    const at = Date.parse(bar.time)
    const frame = byTime.get(at)
    if (!frame || ambiguous.has(at) || bar.confirmed === false ||
        !bar.sourceBarSha256 || bar.sourceBarSha256 !== frame.source_bar_sha256 ||
        bar.trading_day !== frame.trading_day || bar.physicalContract !== frame.physical_contract) {
      active = new Map()
      owner = undefined
      continue
    }
    matched.push(frame)
    const formulaVersion = frame.formula_versions?.join(' / ') || null
    const nextOwner = JSON.stringify([frame.physical_contract, frame.calculation_segment_id, frame.formula_versions])
    if (owner !== nextOwner) active = new Map()
    owner = nextOwner
    for (const [key, style] of Object.entries(PRICE_LINES)) {
      const raw = frame.main_values[key]
      const value = typeof raw === 'string' ? Number(raw) : NaN
      if (!Number.isFinite(value) || value <= 0) {
        active.delete(key)
        continue
      }
      let line = active.get(key)
      if (!line) {
        line = { id: `${key}:${frame.bar_end}`, ...style, sourceRevision, formulaVersion, points: [] }
        active.set(key, line)
        lines.set(line.id, line)
      }
      line.points.push({ time: bar.time, value })
    }
    for (const action of frame.actions) {
      if (action.trade_eligibility === 'WARMUP_ONLY' || action.trade_eligibility === 'NO_ELIGIBLE_ENTRY') continue
      const build = action.kind === 'BUILD' || action.kind === 'OPEN_LONG'
      if (!build && action.kind !== 'CLEAR' && action.kind !== 'CLOSE') continue
      const id = action.signal_id ?? action.source_signal_id
      if (typeof id !== 'string' || !id) continue
      markers.push({
        id, time: bar.time,
        label: build ? '盘后参考建仓' : action.trade_eligibility === 'INITIAL_CLEAR_NO_ENTRY' ? '盘后参考清仓（无入场）' : '盘后参考清仓',
        shape: build ? 'arrowUp' : 'arrowDown',
        position: build ? 'belowBar' : 'aboveBar', tone: build ? 'up' : 'down',
      })
    }
  }
  return { markers, lines: [...lines.values()].filter(line => line.points.length > 1).slice(-64), matched }
}
