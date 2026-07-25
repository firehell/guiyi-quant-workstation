export interface HtdyAlertLinkSource {
  id: number
  symbol: string
  actual_contract: string
  bar_end: string
}

export function buildHtdyAlertMarketQuery(alert: HtdyAlertLinkSource) {
  return {
    symbol: alert.symbol.toLowerCase(),
    contract: alert.actual_contract.toUpperCase(),
    period: '15m',
    data_mode: 'live',
    access_mode: 'browser',
    time: alert.bar_end,
    htdy_alert_id: String(alert.id),
  }
}

export function htdyDirectionLabel(direction: string) {
  if (direction === 'long') return '买多观察'
  if (direction === 'short') return '卖空观察'
  if (direction === 'conflict') return '多空冲突观察'
  return '观察'
}
