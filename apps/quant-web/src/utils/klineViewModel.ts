import type { BarData, HoverKlineContext, KlineMarker, MainIndicatorId, MainIndicatorValue, SeriesKind } from '../types/market.ts'
import { calculateEMA, calculateHuoTianDaYou, calculateMACD } from './indicators.ts'
import { MAIN_INDICATOR_DEFINITIONS } from './mainIndicators.ts'
import type { MainForceMirrorFuturesResult } from './mainForceMirrorFutures.ts'

type EmaIndicatorId = 'ema_10' | 'ema_21' | 'ema_60'

export interface KlineValuePoint {
  time: string
  value: number
}

export interface KlineDerivedData {
  ema: Partial<Record<EmaIndicatorId, KlineValuePoint[]>>
  macd: {
    dif: KlineValuePoint[]
    dea: KlineValuePoint[]
    histogram: KlineValuePoint[]
  }
  htdy: HtdyDerivedData | null
}

export interface HtdyDerivedData {
  zk1: KlineValuePoint[]
  zd1: KlineValuePoint[]
  zd2: KlineValuePoint[]
  markers: KlineMarker[]
}

export type MainForceFuturesAvailabilityKind =
  | 'unsupported'
  | 'input_unavailable'
  | 'derived_unavailable'
  | 'state_warmup'
  | 'caution_warmup'
  | 'conflict'
  | 'ready'

export interface MainForceFuturesAvailability {
  kind: MainForceFuturesAvailabilityKind
  reason: string | null
}

export interface MainForceFuturesSupport {
  period: string
  seriesKind: SeriesKind
}

export interface MainForceFuturesRenderModel {
  histogram: Array<{ time: string; value: number; colorKey: 'up' | 'down' | 'ema21' | 'macdDif' | 'textMuted' }>
  markers: Array<{ time: string; position: 'aboveBar' | 'belowBar'; shape: 'arrowDown' | 'arrowUp'; tone: 'up' | 'down'; text: string }>
  autoscale: { minValue: number; maxValue: number }
}

const MAIN_FORCE_FUTURES_AUTOSCALE = { minValue: -105, maxValue: 105 } as const
const DERIVED_UNAVAILABLE_REASONS = new Set([
  'MFM_FUTURES_V1_ATR_INVALID',
  'MFM_FUTURES_V1_VOLUME_BASELINE_INVALID',
  'MFM_FUTURES_V1_RANGE_INVALID',
])

/** Maps frozen V1 support and point reasons to one user-visible availability contract. */
export function resolveMainForceFuturesAvailability(
  support: MainForceFuturesSupport,
  point: MainForceMirrorFuturesResult['points'][number] | null,
  fallbackReason: string | null,
): MainForceFuturesAvailability {
  if (support.period !== '60m') return { kind: 'unsupported', reason: 'MFM_FUTURES_V1_FREQUENCY_UNSUPPORTED' }
  if (support.seriesKind !== 'contract' && support.seriesKind !== 'actual_dominant') {
    return { kind: 'unsupported', reason: 'MFM_FUTURES_V1_SERIES_UNSUPPORTED' }
  }
  if (!point) return { kind: 'state_warmup', reason: fallbackReason || 'MFM_FUTURES_V1_WARMUP' }
  if (!point.valid) return { kind: 'input_unavailable', reason: point.reason || fallbackReason || 'MFM_FUTURES_V1_INPUT_INVALID' }
  if (point.reason && DERIVED_UNAVAILABLE_REASONS.has(point.reason)) {
    return { kind: 'derived_unavailable', reason: point.reason }
  }
  if (!point.state_ready) return { kind: 'state_warmup', reason: point.reason || 'MFM_FUTURES_V1_WARMUP' }
  if (!point.caution_ready) {
    return { kind: 'caution_warmup', reason: point.caution_availability_reason || 'MFM_FUTURES_V1_CAUTION_WARMUP' }
  }
  if (point.caution_availability_reason === 'MFM_FUTURES_V1_CAUTION_DIRECTION_CONFLICT') {
    return { kind: 'conflict', reason: point.caution_availability_reason }
  }
  return { kind: 'ready', reason: null }
}

/** Resolves the pane from the current logical viewport, never from the loaded tail. */
export function resolveMainForceFuturesWindowAvailability(
  support: MainForceFuturesSupport,
  points: MainForceMirrorFuturesResult['points'],
  range: { from: number; to: number } | null,
): MainForceFuturesAvailability {
  const identity = resolveMainForceFuturesAvailability(support, null, null)
  if (identity.kind === 'unsupported') return identity
  if (!range || !points.length) return resolveMainForceFuturesAvailability(support, null, null)
  const from = Math.max(0, Math.ceil(range.from))
  const to = Math.min(points.length - 1, Math.floor(range.to))
  const visible = points.slice(from, to + 1)
  if (!visible.length) return resolveMainForceFuturesAvailability(support, null, null)
  const stateReady = visible.filter((point) => point.state_ready)
  if (stateReady.length) return resolveMainForceFuturesAvailability(support, stateReady.at(-1) ?? null, null)
  return visible
    .map((point) => resolveMainForceFuturesAvailability(support, point, null))
    .sort((left, right) => unavailablePriority(left) - unavailablePriority(right))[0]
    ?? resolveMainForceFuturesAvailability(support, null, null)
}

function unavailablePriority(availability: MainForceFuturesAvailability): number {
  const reason = availability.reason
  if (reason === 'MFM_FUTURES_V1_SEGMENT_CONFLICT') return 3
  if (reason === 'MFM_FUTURES_V1_PHYSICAL_CONTRACT_MISSING') return 4
  if (reason === 'MFM_FUTURES_V1_TIMESTAMP_INVALID') return 5
  if (reason === 'MFM_FUTURES_V1_OPEN_INTEREST_UNAVAILABLE') return 6
  if (reason === 'MFM_FUTURES_V1_INPUT_INVALID') return 7
  if (availability.kind === 'state_warmup') return 8
  if (availability.kind === 'derived_unavailable') return 9
  if (availability.kind === 'caution_warmup') return 10
  if (availability.kind === 'conflict') return 11
  return 12
}

/** Pure V1 secondary-pane projection: signed scores and directional markers never share numeric data. */
export function buildMainForceFuturesRenderModel(result: MainForceMirrorFuturesResult | null): MainForceFuturesRenderModel {
  const model: MainForceFuturesRenderModel = { histogram: [], markers: [], autoscale: { ...MAIN_FORCE_FUTURES_AUTOSCALE } }
  if (!result) return model
  for (const point of result.points) {
    if (point.signed_score !== null && point.state !== null) {
      const colorKey = point.state === 'long_build' ? 'up'
        : point.state === 'short_build' ? 'down'
          : point.state === 'short_cover' ? 'ema21'
            : point.state === 'long_liquidation' ? 'macdDif' : 'textMuted'
      model.histogram.push({ time: point.time, value: point.signed_score, colorKey })
    }
    if (!point.caution) continue
    const isLong = point.caution === 'long_chase_caution'
    const score = isLong ? point.long_caution_score : point.short_caution_score
    if (score === null) continue
    model.markers.push({
      time: point.time,
      position: isLong ? 'aboveBar' : 'belowBar',
      shape: isLong ? 'arrowDown' : 'arrowUp',
      tone: isLong ? 'up' : 'down',
      text: `${isLong ? '追多小心' : '追空小心'} ${score}`,
    })
  }
  return model
}

/** Formats a nullable chart observation without inventing a numeric fallback. */
export function formatKlineHoverValue(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—'
  return value.toLocaleString('zh-CN', { maximumFractionDigits: 4 })
}

const EMA_PERIODS: Record<EmaIndicatorId, number> = {
  ema_10: 10,
  ema_21: 21,
  ema_60: 60,
}

/**
 * 浏览器侧只负责将已有、已验证的观察镜像整理为图表数据。
 * 指标业务口径仍以 quant-core Indicator Kernel 为权威。
 */
export function buildKlineDerivedData(
  bars: BarData[],
  visibleMainIndicators: MainIndicatorId[],
): KlineDerivedData {
  const ema: KlineDerivedData['ema'] = {}

  for (const indicator of visibleMainIndicators) {
    if (!isEmaIndicator(indicator)) continue
    ema[indicator] = calculateEMA(bars, EMA_PERIODS[indicator]).map(toKlineValuePoint)
  }

  const macd = calculateMACD(bars)
  return {
    ema,
    macd: {
      dif: macd.dif.map(toKlineValuePoint),
      dea: macd.dea.map(toKlineValuePoint),
      histogram: macd.histogram.map(toKlineValuePoint),
    },
    htdy: visibleMainIndicators.includes('htdy') ? buildHtdyDerivedData(bars) : null,
  }
}

function buildHtdyDerivedData(bars: BarData[]): HtdyDerivedData {
  const observation = calculateHuoTianDaYou(bars)
  return {
    zk1: observation.points.flatMap((point) => htdyValuePoint(point.time, point.zk1)),
    zd1: observation.points.flatMap((point) => htdyValuePoint(point.time, point.zd1)),
    zd2: observation.points.flatMap((point) => htdyValuePoint(point.time, point.zd2)),
    markers: observation.points.flatMap((point) => [
      point.buyObservation ? observationMarker(point.time, '买观察', 'belowBar', 'arrowUp') : null,
      point.sellObservation ? observationMarker(point.time, '卖观察', 'aboveBar', 'arrowDown') : null,
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
): KlineMarker {
  return {
    id: `htdy:${label}:${String(time)}`,
    time: String(time),
    label,
    tooltip: '火天大有原始观察；未来引用/重绘风险，仅供人工观察',
    tone: 'htdy',
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
  mainForceFutures: MainForceMirrorFuturesResult | null = null,
  mainForceFuturesSupport: MainForceFuturesSupport = { period: '60m', seriesKind: 'contract' },
): HoverKlineContext | null {
  const bar = bars.find((item) => item.time === time)
  if (!bar) return null

  return {
    time,
    bar,
    mainIndicators: visibleMainIndicators
      .filter(isEmaIndicator)
      .map((indicator) => toHoverIndicatorValue(indicator, pointValue(derived.ema[indicator], time))),
    macd: {
      dif: pointValue(derived.macd.dif, time),
      dea: pointValue(derived.macd.dea, time),
      histogram: pointValue(derived.macd.histogram, time),
    },
    mainForceFutures: toMainForceFuturesHover(mainForceFutures, time, mainForceFuturesSupport),
  }
}

function toMainForceFuturesHover(result: MainForceMirrorFuturesResult | null, time: string, support: MainForceFuturesSupport) {
  const point = result?.points.find((item) => item.time === time)
  if (!point) return null
  const availability = resolveMainForceFuturesAvailability(support, point, null)
  return {
    physicalContract: point.physical_contract,
    valid: point.valid,
    stateReady: point.state_ready,
    cautionReady: point.caution_ready,
    ready: point.ready,
    pointReason: point.reason,
    cautionAvailabilityReason: point.caution_availability_reason,
    state: point.state,
    strength: point.strength,
    priceImpulse: point.price_impulse,
    clv: point.clv,
    volumeRatio: point.volume_ratio,
    deltaOi: point.delta_oi,
    oiImpulse: point.oi_impulse,
    rangePosition: point.range_position,
    longScore: point.long_caution_score,
    shortScore: point.short_caution_score,
    caution: point.caution,
    reasonCodes: point.caution_reason_codes,
    availabilityKind: availability.kind,
    availabilityReason: availability.reason,
  }
}

function isEmaIndicator(indicator: MainIndicatorId): indicator is EmaIndicatorId {
  return indicator in EMA_PERIODS
}

function toKlineValuePoint(point: { time: unknown; value: number }): KlineValuePoint {
  return { time: String(point.time), value: point.value }
}

function pointValue(points: KlineValuePoint[] | undefined, time: string): number | null {
  return points?.find((point) => point.time === time)?.value ?? null
}

function toHoverIndicatorValue(indicator: EmaIndicatorId, value: number | null): MainIndicatorValue {
  const definition = MAIN_INDICATOR_DEFINITIONS.find((item) => item.id === indicator)
  return {
    id: indicator,
    displayName: definition?.displayName || indicator,
    value,
    ready: value !== null,
    valid: true,
    reason: value === null ? 'warming_up' : null,
  }
}
