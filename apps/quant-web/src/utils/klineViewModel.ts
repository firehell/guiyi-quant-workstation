import { formatDisplayNumber } from './marketDisplay.ts'
import type { BarData, HoverKlineContext, KlineMarker, MainIndicatorId, MainIndicatorValue } from '../types/market.ts'
import { calculateHuoTianDaYou } from './indicators.ts'
import { MAIN_INDICATOR_DEFINITIONS } from './mainIndicators.ts'
import { isEmaIndicator, type EmaIndicatorId, type MarketChartStudyPoint, type MarketChartStudyPoints } from './marketChartStudies.ts'
import { calculateRangeDetectorLux, type RangeDetectorLuxResult, type RangeDetectorSnapshot } from './rangeDetectorLux.ts'
import { calculateThsMacdDisplay } from './thsMacdDisplay.ts'

export interface KlineValuePoint {
  time: string
  value: number | null
}

export interface KlineDerivedData {
  ema: Partial<Record<EmaIndicatorId, KlineValuePoint[]>>
  emaFacts: MarketChartStudyPoints
  macd: ReturnType<typeof calculateThsMacdDisplay>
  htdy: HtdyDerivedData | null
  rangeDetector: RangeDetectorLuxResult | null
}

export interface KlineDerivedOptions {
  hideThsMacd?: boolean
  emaPoints?: MarketChartStudyPoints
  rangeDetector?: {
    enabled: boolean
    sourceIdentity: string
    anchorTime: string | null
  }
}

export interface HtdyDerivedData {
  zk1: KlineValuePoint[]
  zd1: KlineValuePoint[]
  zd2: KlineValuePoint[]
  markers: KlineMarker[]
}

/** Formats a nullable chart observation without inventing a numeric fallback. */
export function formatKlineHoverValue(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—'
  return formatDisplayNumber(value, true)
}

/**
 * 通用 EMA 只投影服务端事实。专属同花顺 MACD 与 HTDY 观察保持各自公式。
 */
export function buildKlineDerivedData(
  bars: BarData[],
  visibleMainIndicators: MainIndicatorId[],
  options: KlineDerivedOptions = {},
): KlineDerivedData {
  const ema: KlineDerivedData['ema'] = {}
  const emaFacts = options.emaPoints ?? {}
  for (const indicator of visibleMainIndicators) {
    if (!isEmaIndicator(indicator) || ema[indicator]) continue
    const facts = emaFacts[indicator]
    ema[indicator] = chartStudySeries(bars, facts, 'value')
  }

  const anchoredBars = options.rangeDetector?.anchorTime
    ? bars.filter((bar) => Date.parse(bar.time) >= Date.parse(options.rangeDetector!.anchorTime!))
    : []
  const rangeDetector = options.rangeDetector?.enabled && options.rangeDetector.anchorTime
    ? buildSegmentedRangeDetector(anchoredBars, options.rangeDetector.sourceIdentity)
    : null
  return {
    ema,
    emaFacts,
    macd: calculateThsMacdDisplay(options.hideThsMacd ? [] : bars),
    htdy: visibleMainIndicators.includes('htdy') ? buildHtdyDerivedData(bars) : null,
    rangeDetector,
  }
}

export function chartStudySeries(
  bars: readonly BarData[], facts: Record<string, MarketChartStudyPoint> | undefined, output: string,
  completedFacts?: Record<string, MarketChartStudyPoint>,
): KlineValuePoint[] {
  if (!facts && !completedFacts) return []
  return bars.flatMap(bar => {
    const point = bar.marketSource === 'completed_live' ? completedFacts?.[bar.time]
      : bar.confirmed !== false ? facts?.[bar.time] : undefined
    return point ? [{ time: bar.time, value: point.values?.[output] ?? null }] : []
  })
}

/** Physical/quality ownership limits the kernel warm-up just like its input validity reset. */
function buildSegmentedRangeDetector(bars: BarData[], sourceIdentity: string): RangeDetectorLuxResult {
  const segments: BarData[][] = []
  let current: BarData[] = []
  for (const bar of bars) {
    const previous = current.at(-1)
    if (previous && (previous.physicalContract !== bar.physicalContract || previous.calculationSegmentId !== bar.calculationSegmentId)) {
      if (Date.parse(previous.time) >= Date.parse(bar.time)) throw new Error('bar times must be strictly increasing')
      segments.push(current)
      current = []
    }
    current.push(bar)
  }
  if (current.length) segments.push(current)
  const merged: RangeDetectorLuxResult = { points: [], ranges: [] }
  segments.forEach((segment, index) => {
    const first = segment[0]!
    // No positional segment index: prepending another owner cannot rename an existing segment.
    const identity = segments.length === 1
      ? sourceIdentity
      : JSON.stringify([sourceIdentity, first.physicalContract ?? null, first.calculationSegmentId ?? null, first.time])
    const result = calculateRangeDetectorLux(segment, { sourceIdentity: identity })
    const lastTime = segment.at(-1)!.time
    merged.points.push(...result.points)
    merged.ranges.push(...result.ranges.map(range => index < segments.length - 1 && range.levelsActiveUntil === null
      ? { ...range, levelsActiveUntil: lastTime }
      : range))
  })
  return merged
}

function buildHtdyDerivedData(bars: BarData[]): HtdyDerivedData {
  const observation = calculateHuoTianDaYou(bars)
  return {
    zk1: observation.points.flatMap((point) => htdyValuePoint(point.time, point.zk1)),
    zd1: observation.points.flatMap((point) => htdyValuePoint(point.time, point.zd1)),
    zd2: observation.points.flatMap((point) => htdyValuePoint(point.time, point.zd2)),
    markers: observation.points.flatMap((point) => [
      point.buyObservation ? observationMarker(point.time, '买观察', 'belowBar', 'arrowUp', 'up') : null,
      point.sellObservation ? observationMarker(point.time, '卖观察', 'aboveBar', 'arrowDown', 'down') : null,
    ].filter((marker): marker is KlineMarker => marker !== null)),
  }
}

function htdyValuePoint(time: unknown, value: number | null): KlineValuePoint[] {
  return value === null ? [] : [{ time: String(time), value }]
}

function observationMarker(
  time: unknown,
  label: string,
  position: KlineMarker['position'],
  shape: KlineMarker['shape'],
  tone: KlineMarker['tone'],
): KlineMarker {
  return {
    id: `htdy:${label}:${String(time)}`,
    time: String(time),
    label,
    tooltip: '火天大有原始观察；未来引用/重绘风险，仅供人工观察',
    tone,
    position,
    shape,
  }
}

/** Returns one timestamp-aligned observation for the synchronized chart crosshair. */
export function resolveKlineHoverContext(
  bars: BarData[],
  derived: KlineDerivedData,
  visibleMainIndicators: MainIndicatorId[],
  time: string,
  markers: KlineMarker[] = [],
): HoverKlineContext | null {
  const bar = bars.find((item) => item.time === time)
  if (!bar) return null

  return {
    time,
    bar,
    mainIndicators: hoverEmaIndicators(visibleMainIndicators).map((indicator) => (
      toHoverIndicatorValue(indicator, pointValue(derived.ema[indicator], time), derived.emaFacts[indicator]?.[time])
    )),
    macd: {
      dif: pointValue(derived.macd.dif, time),
      dea: pointValue(derived.macd.dea, time),
      histogram: pointValue(derived.macd.histogram, time),
    },
    rangeDetector: resolveRangeDetectorHoverFact(derived.rangeDetector, time),
    marker: markers.find((marker) => sameMarkerTime(marker.time, time)) ?? null,
  }
}

function resolveRangeDetectorHoverFact(
  rangeDetector: RangeDetectorLuxResult | null,
  time: string,
): HoverKlineContext['rangeDetector'] {
  if (!rangeDetector) return null
  const hoverAt = Date.parse(time)
  if (!Number.isFinite(hoverAt)) return null
  const rangesByKey = new Map(rangeDetector.ranges.map((range) => [range.key, range]))
  for (let index = rangeDetector.points.length - 1; index >= 0; index -= 1) {
    const point = rangeDetector.points[index]!
    const snapshot = point.snapshot
    if (!snapshot || Date.parse(point.time) > hoverAt) continue
    const visualRange = rangesByKey.get(`${snapshot.rangeId}:${snapshot.revision}`)
    if (!isActiveRangeSnapshot(snapshot, visualRange?.levelsActiveUntil ?? null, hoverAt)) continue
    return {
      rangeId: snapshot.rangeId,
      revision: snapshot.revision,
      state: snapshot.state,
      upper: snapshot.currentUpper,
      lower: snapshot.currentLower,
      mid: snapshot.currentMid,
      confirmedAt: snapshot.confirmedAt,
      visualStartAt: snapshot.visualStartAt,
    }
  }
  return null
}

function isActiveRangeSnapshot(
  snapshot: RangeDetectorSnapshot,
  levelsActiveUntil: string | null,
  hoverAt: number,
): boolean {
  const startsAt = Date.parse(snapshot.levelsActiveFrom)
  if (!Number.isFinite(startsAt) || hoverAt < startsAt) return false
  if (!levelsActiveUntil) return true
  const endsAt = Date.parse(levelsActiveUntil)
  return Number.isFinite(endsAt) && hoverAt <= endsAt
}

function sameMarkerTime(left: string, right: string): boolean {
  const leftTimestamp = Date.parse(left)
  const rightTimestamp = Date.parse(right)
  if (Number.isFinite(leftTimestamp) && Number.isFinite(rightTimestamp)) {
    return leftTimestamp === rightTimestamp
  }
  return left === right
}

function hoverEmaIndicators(
  visibleMainIndicators: MainIndicatorId[],
): EmaIndicatorId[] {
  const ids: EmaIndicatorId[] = []
  for (const indicator of visibleMainIndicators) {
    if (!isEmaIndicator(indicator) || ids.includes(indicator)) continue
    ids.push(indicator)
  }
  return ids
}

function pointValue(points: KlineValuePoint[] | undefined, time: string): number | null {
  return points?.find((point) => point.time === time)?.value ?? null
}

function toHoverIndicatorValue(
  indicator: EmaIndicatorId, value: number | null, point?: NonNullable<MarketChartStudyPoints[EmaIndicatorId]>[string],
): MainIndicatorValue {
  const definition = MAIN_INDICATOR_DEFINITIONS.find((item) => item.id === indicator)
  return {
    id: indicator,
    displayName: definition?.displayName || indicator,
    value,
    ready: value !== null,
    valid: value !== null || point?.status === 'WARMING',
    reason: value === null ? point?.diagnostic ?? 'missing_input' : null,
  }
}
