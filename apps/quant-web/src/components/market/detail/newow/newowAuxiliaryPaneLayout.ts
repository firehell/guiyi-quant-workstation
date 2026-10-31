import { detailChartPaneLayout } from '../../../../utils/detailChartSession.ts'

/** Public PC auxiliary plot is 110 CSS px; keep the shared pane/axis model. */
export function newowAuxiliaryPaneLayout(chartHeight: number, toolbarHeight: number) {
  return detailChartPaneLayout(chartHeight, toolbarHeight, 110)
}
