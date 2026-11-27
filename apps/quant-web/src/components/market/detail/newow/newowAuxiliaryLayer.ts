import type { Time } from 'lightweight-charts'
import type { LayerDiagnostics } from '@guiyi/quant-chart'
import type { NewowProductSectionResponse, NewowResourceLifecycle } from '../../../../types/newowProduct.ts'
import { lookupKeyFromChartTime } from '../../../../utils/barTime.ts'
import { newowAuxiliaryLayerStatus } from '../../../../utils/newowAdditionalPanes.ts'
import { projectNewowAuxiliaryReadiness } from '../../../../utils/newowDetailPresentation.ts'
import { chartMarkerTime, type NewowAlignedAuxiliaryChartModel, type NewowProductChartModel } from './newowProductChartPrimitives.ts'
import { NewowZhaoyaoMirrorPrimitive, buildNewowZhaoyaoMirrorData } from './newowZhaoyaoMirrorPrimitive.ts'
import { NewowUpDownEnergyPrimitive, buildNewowUpDownEnergyData } from './newowUpDownEnergyPrimitive.ts'
import { NewowMainForceControlPrimitive, buildNewowMainForceData } from './newowMainForceControlPrimitive.ts'
import { NewowTrendReversalPrimitive, buildNewowTrendReversalData, buildNewowTrendReversalMarks } from './newowTrendReversalPrimitive.ts'

type ChartResponse = NewowProductSectionResponse<'chart'>
type AuxiliaryResponse = NewowProductSectionResponse<'auxiliary'>
export type NewowAuxiliaryPrimitive = NewowZhaoyaoMirrorPrimitive | NewowUpDownEnergyPrimitive | NewowMainForceControlPrimitive | NewowTrendReversalPrimitive

/** Read back the formal Bar end behind the latest point submitted to a renderer. */
export function auxiliaryPaintCutoff(model: NewowProductChartModel | null, tails: readonly (Time | undefined)[]): string | null {
  if (!model) return null
  const keys = new Set(tails.flatMap(time => time === undefined ? [] : [lookupKeyFromChartTime(time)]))
  if (!keys.size) return null
  for (let index = model.bars.length - 1; index >= 0; index--) {
    const bar = model.bars[index]!
    if (keys.has(lookupKeyFromChartTime(chartMarkerTime(bar.barEnd, model.identity.frequency, bar.tradingDay)))) return bar.barEnd
  }
  return null
}

export function paintNewowAuxiliaryPrimitive(
  primitive: NewowAuxiliaryPrimitive,
  value: NewowAlignedAuxiliaryChartModel | null,
  response: AuxiliaryResponse | null | undefined,
  model: NewowProductChartModel | null,
  topInset: number,
  decorations?: { mirrorEvents: Parameters<typeof buildNewowZhaoyaoMirrorData>[1] },
): string | null {
  const series = value?.series ?? []
  if (primitive instanceof NewowZhaoyaoMirrorPrimitive) {
    const data = buildNewowZhaoyaoMirrorData(series, decorations?.mirrorEvents)
    primitive.setData(data, topInset)
    return auxiliaryPaintCutoff(model, [data.at(-1)?.time])
  }
  if (primitive instanceof NewowUpDownEnergyPrimitive) {
    const data = buildNewowUpDownEnergyData(series, model?.bars ?? [])
    primitive.setData(data, topInset)
    for (let index = data.length - 1; index >= 0; index--) {
      const row = data[index]!
      if (row.previous !== null || row.signal !== null) return auxiliaryPaintCutoff(model, [row.time])
    }
    return null
  }
  if (primitive instanceof NewowMainForceControlPrimitive) {
    const data = response?.value?.component === 'main_force_control' ? buildNewowMainForceData(series, response.value.segments) : []
    primitive.setData(data, topInset)
    return auxiliaryPaintCutoff(model, [data.at(-1)?.time])
  }
  const data = buildNewowTrendReversalData(series)
  const marks = decorations && model && response?.value?.component === 'trend_reversal'
    ? buildNewowTrendReversalMarks(model, response.value.segments) : []
  primitive.setData(data, topInset, marks)
  return auxiliaryPaintCutoff(model, [data.at(-1)?.time, ...marks.map(mark => mark.time)])
}

export function newowAuxiliaryDiagnostics(options: {
  chart: ChartResponse | null
  response: AuxiliaryResponse | null | undefined
  aligned: boolean
  lifecycle: NewowResourceLifecycle
  error: string | null
  dataCutoff: string | null
}): Pick<LayerDiagnostics, 'status' | 'sourceIdentity' | 'formulaVersion' | 'frequency' | 'dataCutoff' | 'lastError'> {
  const { chart, response, aligned, lifecycle, error, dataCutoff } = options
  const accepted = aligned ? response : null
  const latest = chart?.value?.bars.at(-1)
  const readiness = projectNewowAuxiliaryReadiness(accepted?.value, latest)
  // The aggregate envelope can be unavailable because a different physical segment failed.
  const effectiveLifecycle = lifecycle === 'unavailable' && accepted?.status?.status === 'unavailable' && readiness && !error
    ? readiness.currentStatus : lifecycle
  const status = newowAuxiliaryLayerStatus(effectiveLifecycle, Boolean(response?.value), aligned,
    readiness?.currentStatus ?? null, dataCutoff !== null && dataCutoff === latest?.bar_end, error)
  const sourceReason = readiness ? readiness.reason : response?.status?.reason_code ?? null
  const reason = error ?? (status === 'invalid_source' ? 'CHART_AUXILIARY_SOURCE_INVALID' : sourceReason)
  const publicCode = reason === 'warming_up' || (reason && /^[A-Z][A-Z0-9_]{0,79}$/.test(reason)) ? reason : null
  return {
    status, sourceIdentity: accepted?.meta.data_revision_identity ?? accepted?.meta.input_content_sha256 ?? null,
    formulaVersion: accepted?.value?.formula_version ?? null, frequency: chart?.meta.identity.frequency ?? null,
    dataCutoff: aligned ? dataCutoff : null,
    lastError: publicCode ?? (status === 'invalid_source' ? 'CHART_AUXILIARY_SOURCE_INVALID'
      : status === 'compute_error' ? 'CHART_AUXILIARY_COMPUTE_FAILED' : null),
  }
}
