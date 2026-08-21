import type {
  MainForceMemberRelation,
  MainForceMirrorV2Point,
  MainForceMirrorV2State,
} from '../types/market.ts'

export type SecondaryPanelId = 'macd' | 'main_force_mirror_v2'

export interface MainForceMirrorV2RenderModel {
  histogram: Array<{
    time: string
    value: number
    colorKey: 'up' | 'down' | 'ema21' | 'macdDif' | 'textMuted'
  }>
  accumulated: Array<{ time: string; value: number }>
  markers: Array<{
    time: string
    position: 'aboveBar' | 'belowBar'
    shape: 'arrowDown' | 'arrowUp'
    tone: 'up' | 'down'
    text: string
  }>
  latest: MainForceMirrorV2Point | null
  autoscale: { minValue: number; maxValue: number }
}

const STATE_COLORS: Record<MainForceMirrorV2State, MainForceMirrorV2RenderModel['histogram'][number]['colorKey']> = {
  long_build: 'up',
  short_build: 'down',
  short_cover: 'ema21',
  long_liquidation: 'macdDif',
  turnover: 'textMuted',
}

export const MAIN_FORCE_MEMBER_RELATION_LABELS: Record<MainForceMemberRelation, string> = {
  strong_aligned: '席位强同向',
  aligned: '席位同向',
  divergent: '席位背离',
  neutral: '席位中性',
  unavailable: '席位不可用',
}

/** Presentation-only projection: all numeric and classification values come from the V2 API. */
export function buildMainForceMirrorV2RenderModel(
  points: MainForceMirrorV2Point[],
): MainForceMirrorV2RenderModel {
  return {
    histogram: points.flatMap((point) => (
      point.instant_pressure === null || point.pressure_state === null
        ? []
        : [{ time: point.bar_end, value: point.instant_pressure, colorKey: STATE_COLORS[point.pressure_state] }]
    )),
    accumulated: points.flatMap((point) => (
      point.accumulated_pressure === null
        ? []
        : [{ time: point.bar_end, value: point.accumulated_pressure }]
    )),
    markers: points.flatMap((point) => {
      if (point.caution === null) return []
      const isLong = point.caution === 'long_chase_caution'
      const score = isLong ? point.long_caution_score : point.short_caution_score
      return [{
        time: point.bar_end,
        position: isLong ? 'aboveBar' as const : 'belowBar' as const,
        shape: isLong ? 'arrowDown' as const : 'arrowUp' as const,
        tone: isLong ? 'up' as const : 'down' as const,
        text: `${isLong ? '追多小心' : '追空小心'} ${score ?? '—'}｜${MAIN_FORCE_MEMBER_RELATION_LABELS[point.relation_to_caution]}`,
      }]
    }),
    latest: points.at(-1) ?? null,
    autoscale: { minValue: -105, maxValue: 105 },
  }
}

export function normalizeSecondaryPanelPreference(value: unknown): SecondaryPanelId {
  if (value === 'main_force_mirror_futures') return 'main_force_mirror_v2'
  return value === 'main_force_mirror_v2' ? value : 'macd'
}
