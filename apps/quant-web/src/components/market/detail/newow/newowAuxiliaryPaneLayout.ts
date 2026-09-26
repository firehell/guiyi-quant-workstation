/** Toolbar height is separate from the indicator's usable plot, including on wrapped layouts. */
export function newowAuxiliaryPaneLayout(chartHeight: number, toolbarHeight: number) {
  const topInset = Math.max(44, toolbarHeight + 12)
  const auxiliaryHeight = topInset + 215
  const volumeHeight = Math.max(80, Math.min(130, chartHeight * 0.12))
  // Native chart reserves the shared time axis and two pane separators.
  const mainHeight = Math.max(1, chartHeight - 30 - volumeHeight - auxiliaryHeight)
  return { topInset, auxiliaryHeight, volumeHeight, mainHeight }
}
