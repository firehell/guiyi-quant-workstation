import { detailChartPaneLayout } from '../../../../utils/detailChartSession.ts'

/** Public PC auxiliary plot is 110 CSS px; keep the shared pane/axis model. */
export function newowAuxiliaryPaneLayout(chartHeight: number, toolbarHeight: number) {
  const layout = detailChartPaneLayout(chartHeight, toolbarHeight, 110)
  // Volume is overlaid in the main pane, not a third native pane.
  return { topInset: layout.topInset, auxiliaryHeight: layout.auxiliaryHeight, mainHeight: layout.mainHeight }
}
