import { DISPLAY_CATALOG, type ChartHost } from '@guiyi/quant-chart'
import type { ISeriesApi, Time } from 'lightweight-charts'
import type { ArchivePane, PaneId } from '../../../../utils/workstationChartPanes.ts'
import { newowPaneId } from '../../../../utils/newowAdditionalPanes.ts'
import { alignNewowAuxiliaryChartModel, buildNewowProductChartModel } from './newowProductChartPrimitives.ts'
import { newowAuxiliaryDiagnostics, paintNewowAuxiliaryPrimitive } from './newowAuxiliaryLayer.ts'
import { NewowZhaoyaoMirrorPrimitive } from './newowZhaoyaoMirrorPrimitive.ts'
import { NewowUpDownEnergyPrimitive } from './newowUpDownEnergyPrimitive.ts'
import { NewowMainForceControlPrimitive } from './newowMainForceControlPrimitive.ts'
import { NewowTrendReversalPrimitive } from './newowTrendReversalPrimitive.ts'

const constructors = {
  main_force_control: NewowMainForceControlPrimitive, trend_reversal: NewowTrendReversalPrimitive,
  up_down_energy: NewowUpDownEnergyPrimitive, zhaoyao_mirror: NewowZhaoyaoMirrorPrimitive,
}
export function createWorkstationPaneRenderer() {
  const anchors = new Map<PaneId, ISeriesApi<'Line'>>()
  const painted = new Map<PaneId, ArchivePane>()
  const cursorValues = new Map<PaneId, Map<string, string[]>>()
  function render(host: ChartHost, panes: readonly ArchivePane[], times: Time[]) {
    for (const id of anchors.keys()) if (!panes.some(pane => pane.id === id)) {
      host.removeAuxiliary(id)
      anchors.delete(id)
      painted.delete(id)
      cursorValues.delete(id)
    }
    for (const pane of panes) {
      const target = host.addAuxiliary(pane.id)
      const axisId = 'workstation-axis:' + pane.id
      const ok = host.renderLayer(axisId, 'auxiliary_axis', target, 'line', layer => {
        let anchor = anchors.get(pane.id)
        if (!anchor) {
          anchor = layer.line({ visible: true, lineVisible: false, lastValueVisible: false, priceLineVisible: false, crosshairMarkerVisible: false })
          anchors.set(pane.id, anchor)
        }
        anchor.setData(times.map(time => ({ time })))
      })
      if (!ok) {
        anchors.delete(pane.id)
        painted.delete(pane.id)
        host.removeAuxiliary(pane.id)
        continue
      }
      if (pane.id === 'macd' || painted.get(pane.id) === pane) continue
      const id = newowPaneId(pane.id)
      host.removeLayer(id)
      const component = pane.id
      cursorValues.delete(component)
      const ready = host.renderLayer(id, id, target, 'primitive', layer => {
        const model = pane.chart ? buildNewowProductChartModel(pane.chart) : null
        const aligned = alignNewowAuxiliaryChartModel(pane.chart, pane.auxiliary)
        const primitive = new constructors[component]()
        let cutoff: string | null = null
        if (aligned?.component === component && model) {
          const values = new Map<string, string[]>()
          for (const series of aligned.series) for (const point of series.points) {
            const key = point.physicalContract + '/' + Date.parse(point.barEnd)
            let labels = values.get(key)
            if (!labels) values.set(key, labels = [])
            labels.push(series.label + ' ' + Number(point.value.toFixed(3)))
          }
          cursorValues.set(component, values)
          layer.primitive(anchors.get(component)!, primitive)
          cutoff = paintNewowAuxiliaryPrimitive(primitive, aligned, pane.auxiliary, model, 23)
        }
        layer.updateDiagnostics(newowAuxiliaryDiagnostics({ chart: pane.chart, response: pane.auxiliary,
          aligned: aligned?.component === component, lifecycle: pane.auxiliary?.status.status ?? 'not_requested',
          error: null, dataCutoff: cutoff }))
      })
      if (ready) painted.set(pane.id, pane)
    }
    host.orderAuxiliaries(panes.filter(pane => anchors.has(pane.id)).map(pane => pane.id))
  }
  function headers(host: ChartHost, panes: readonly ArchivePane[]) {
    return panes.filter(pane => anchors.has(pane.id)).map(pane => {
      const index = host.paneIndex({ auxiliary: pane.id })
      const top = host.chart.panes().slice(0, index).reduce((sum, p) => sum + p.getHeight(), 0)
      const id = newowPaneId(pane.id)
      const status = host.inspectLayer(pane.id === 'macd' ? 'talib-macd' : id)?.status
      const label = pane.id === 'macd' ? 'MACD (12, 26, 9)' : DISPLAY_CATALOG[id]!.label
      return { id, component: pane.id, top, label, note: pane.message ?? (status === 'ready' ? null : status === 'warming' ? '预热中' : '当前指标不可用'),
        retrospective: DISPLAY_CATALOG[id]?.retrospective === true }
    })
  }
  function readout(id: PaneId, bar: { time: string; physicalContract?: string }) {
    return cursorValues.get(id)?.get(bar.physicalContract + '/' + Date.parse(bar.time))?.join(' · ') ?? '该 Bar 无指标值'
  }
  return { render, headers, readout }
}
