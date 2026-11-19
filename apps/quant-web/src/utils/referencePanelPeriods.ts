/** Active reference presentation is Newow-only; alerts and account records are independent. */
export function referencePanelSupported(strategy: string, frequency: string, seriesKind?: string): boolean {
  if (seriesKind && seriesKind !== 'actual_dominant') return false
  return ['newow_trend', 'newow_oscillation', 'newow_main_rise', 'newow_dual_fusion'].includes(strategy.replaceAll('-', '_'))
    && ['5m', '15m', '30m', '60m', '1d', '1w'].includes(frequency)
}
