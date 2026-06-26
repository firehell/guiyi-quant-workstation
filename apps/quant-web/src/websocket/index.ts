import { WsClient } from './WsClient'
import type { SignalRecord } from '@/types/signal'

const wsUrl = import.meta.env.VITE_WS_URL || 'ws://localhost:8000/ws'

export const wsClient = new WsClient(wsUrl)

/** 订阅实时信号 */
export function subscribeSignals(callback: (signal: SignalRecord) => void) {
  wsClient.on('signal', callback as (data: unknown) => void)
  wsClient.send('subscribe', { channel: 'signal' })
}

/** 订阅行情推送 */
export function subscribeQuote(symbol: string, callback: (data: unknown) => void) {
  wsClient.on(`quote.${symbol}`, callback)
  wsClient.send('subscribe', { channel: 'quote', symbol })
}

/** 取消订阅行情 */
export function unsubscribeQuote(symbol: string) {
  wsClient.send('unsubscribe', { channel: 'quote', symbol })
}

export function backtestTaskWsUrl(taskNo: string) {
  const configured = import.meta.env.VITE_WS_URL || 'ws://localhost:8000/ws'
  const base = configured.endsWith('/ws') ? configured.slice(0, -3) : configured
  return `${base}/ws/backtests/${taskNo}`
}

export function signalWsUrl() {
  const configured = import.meta.env.VITE_WS_URL || 'ws://localhost:8000/ws'
  const base = configured.endsWith('/ws') ? configured.slice(0, -3) : configured
  return `${base}/ws/signals`
}
