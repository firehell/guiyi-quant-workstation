import { MAX_AUXILIARY_PANES } from '@guiyi/quant-chart'
import { NEWOW_EXTRA_AUXILIARY_OPTIONS, type NewowAuxiliaryPaneComponent } from './newowAdditionalPanes.ts'
import type { MarketAfterCloseFrame, MarketAfterCloseSection } from '../types/referenceTrading.ts'
import type { BarData } from '../types/market.ts'
import type { NewowProductSectionResponse } from '../types/newowProduct.ts'

export const workstationOverlays = [
  { id: 'ema_10', label: 'EMA10' }, { id: 'ema_21', label: 'EMA21' },
  { id: 'ema_60', label: 'EMA60' }, { id: 'boll', label: 'BOLL (20, 2)' },
] as const
export type WorkstationOverlay = typeof workstationOverlays[number]['id']
export type PaneId = NewowAuxiliaryPaneComponent
export const paneOptions = NEWOW_EXTRA_AUXILIARY_OPTIONS
export interface PaneSpec { id: PaneId; height: number }
export const strokeOptions = [
  ['ema_10', 'EMA10', '#2563eb'], ['ema_21', 'EMA21', '#f59e0b'], ['ema_60', 'EMA60', '#7c3aed'],
  ['boll_edge', 'BOLL 上下轨', '#7c3aed'], ['boll_mid', 'BOLL 中轨', '#f59e0b'],
  ['macd_dif', 'MACD DIF', '#00bfcf'], ['macd_dea', 'MACD DEA', '#d4b000'],
  ['a', '趋势 A', '#b48b16'], ['b', '趋势 B', '#5079b7'], ['upper', '震荡上沿', '#b48b16'], ['lower', '震荡下沿', '#5079b7'],
  ['ma35', 'MA35', '#b48b16'], ['ma45', 'MA45', '#5079b7'], ['ma10_display_v1', 'MA10', '#8b58a6'],
] as const
export type StrokeId = typeof strokeOptions[number][0]
export interface Stroke { color?: string; lineWidth?: 1 | 2 | 3 | 4 }
export type WorkstationStyles = Partial<Record<StrokeId, Stroke>>
export interface WorkstationLayers { overlays: WorkstationOverlay[]; panes: PaneSpec[]; strokes?: WorkstationStyles; logPrice?: boolean }
export function selectPrimaryPane(layers: WorkstationLayers, id: PaneId): WorkstationLayers {
  const [first, ...rest] = layers.panes
  return { ...layers, panes: [{ id, height: first?.height ?? 144 },
    ...rest.map(pane => pane.id === id && first ? { ...pane, id: first.id } : pane)] }
}
export const PANE_HEIGHTS = [96, 144, 200] as const

export function readWorkstationLayers(raw: unknown): WorkstationLayers {
  const source = raw as Partial<WorkstationLayers> | null
  const overlays = workstationOverlays.flatMap(({ id }) => Array.isArray(source?.overlays) && source.overlays.includes(id) ? [id] : [])
  const panes: PaneSpec[] = []
  if (Array.isArray(source?.panes)) for (const row of source.panes) {
    if (row && paneOptions.some(item => item.id === row.id) && !panes.some(item => item.id === row.id)
        && panes.length < MAX_AUXILIARY_PANES) {
      panes.push({ id: row.id, height: PANE_HEIGHTS.some(n => n === row.height) ? row.height : 144 })
    }
  }
  if (!Array.isArray(source?.panes)) panes.push({ id: 'zhaoyao_mirror', height: 144 })
  const strokes: WorkstationStyles = {}
  for (const [id] of strokeOptions) {
    const style = source?.strokes?.[id]
    if (!style || typeof style !== 'object') continue
    const color = typeof style.color === 'string' && /^#[0-9a-f]{6}$/i.test(style.color) ? style.color : undefined
    const lineWidth = style.lineWidth && [1,2,3,4].includes(style.lineWidth) ? style.lineWidth : undefined
    if (color || lineWidth) strokes[id] = { ...(color ? { color } : {}), ...(lineWidth ? { lineWidth } : {}) }
  }
  return { overlays, panes, ...(Object.keys(strokes).length ? { strokes } : {}), ...(source?.logPrice === true ? { logPrice: true } : {}) }
}

export interface ArchivePane extends PaneSpec {
  chart: NewowProductSectionResponse<'chart'> | null
  auxiliary: NewowProductSectionResponse<'auxiliary'> | null
  message: string | null
}

/** Market's matched frames already prove the Canonical SHA. Require the archived
 * section to carry the same completed OHLCV, historical owner and calculation segment. */
export function matchedArchiveChart(section: MarketAfterCloseSection, frames: readonly MarketAfterCloseFrame[], bars: readonly BarData[]) {
  if (section.status !== 'ready' || !section.chart.value) return null
  const current = new Map(bars.map(bar => [Date.parse(bar.time), bar]))
  const matched = new Map(frames.map(frame => [Date.parse(frame.bar_end), frame]))
  const verified = section.chart.value.bars.filter(row => {
    const time = Date.parse(row.bar_end), frame = matched.get(time), bar = current.get(time)
    return row.completed && row.observation_eligible && frame && bar?.marketSource === 'canonical'
      && bar.confirmed !== false && !!bar.sourceBarSha256 && frame.source_bar_sha256 === bar.sourceBarSha256
      && row.physical_contract === frame.physical_contract && bar.physicalContract === row.physical_contract
      && frame.calculation_segment_id === row.calculation_segment_id && !!row.calculation_segment_id
      && bar.trading_day === frame.trading_day && row.trading_day === frame.trading_day
      && Number(row.open) === bar.open && Number(row.high) === bar.high && Number(row.low) === bar.low
      && Number(row.close) === bar.close && row.volume === bar.volume
  })
  return verified.length ? { ...section.chart, value: { ...section.chart.value, bars: verified } } : null
}
