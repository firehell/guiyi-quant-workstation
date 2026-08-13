import type { BarData, HoverKlineContext, KlineMarker, MainIndicatorId, MainIndicatorValue } from '../types/market.ts'
import { calculateEMA, calculateHuoTianDaYou, calculateMACD } from './indicators.ts'
import { MAIN_INDICATOR_DEFINITIONS } from './mainIndicators.ts'

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
      point.buyObservation ? observationMarker(point.time, '买观察', '#2dd4bf', 'belowBar', 'arrowUp') : null,
      point.sellObservation ? observationMarker(point.time, '卖观察', '#f472b6', 'aboveBar', 'arrowDown') : null,
    ].filter((marker): marker is KlineMarker => marker !== null)),
  }
}

function htdyValuePoint(time: unknown, value: number | null): KlineValuePoint[] {
  return value === null ? [] : [{ time: String(time), value }]
}

function observationMarker(
  time: unknown,
  label: string,
  color: string,
  position: KlineMarker['position'],
  shape: KlineMarker['shape'],
): KlineMarker {
  return {
    id: `htdy:${label}:${String(time)}`,
    time: String(time),
    label,
    tooltip: '火天大有原始观察；未来引用/重绘风险，仅供人工观察',
    color,
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
    color: definition?.color || '#94a3b8',
    value,
    ready: value !== null,
    valid: true,
    reason: value === null ? 'warming_up' : null,
  }
}
