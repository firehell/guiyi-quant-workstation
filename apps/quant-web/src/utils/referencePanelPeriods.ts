/** Web presentation policy only; AlertEvent scope and backend audit capabilities stay independent. */
export function referencePanelSupported(strategy: string, frequency: string, seriesKind?: string): boolean {
  if (seriesKind && seriesKind !== 'actual_dominant') return false
  if (strategy === 'htdy') return frequency === '60m'
  return ['subing-reference', 'subing_reference'].includes(strategy)
    && ['15m', '30m', '60m', '1d'].includes(frequency)
}
