import { WsClient } from './WsClient'
import type { SignalRecord } from '@/types/signal'
import { resolveWsURL } from '@/utils/network'
import { resolvedWsUrl } from '@/utils/settings'

const wsUrl = resolveWsURL(resolvedWsUrl() || import.meta.env.VITE_WS_URL)

/** 全局共享 WebSocket 实例，用于信号与行情订阅 */
export const wsClient = new WsClient(wsUrl)

/** 订阅实时信号频道，回调收到 SignalRecord 推送 */
export function subscribeSignals(callback: (signal: SignalRecord) => void) {
  wsClient.on('signal', callback as (data: unknown) => void)
  wsClient.send('subscribe', { channel: 'signal' })
}

/** 订阅指定品种的行情推送，事件名为 quote.{symbol} */
export function subscribeQuote(symbol: string, callback: (data: unknown) => void) {
  wsClient.on(`quote.${symbol}`, callback)
  wsClient.send('subscribe', { channel: 'quote', symbol })
}

/** 取消指定品种的行情订阅 */
export function unsubscribeQuote(symbol: string) {
  wsClient.send('unsubscribe', { channel: 'quote', symbol })
}

/**
 * 构造回测任务进度 WebSocket 地址。
 * 与通用 /ws 端点分离，按 taskNo 独立连接。
 */
export function backtestTaskWsUrl(taskNo: string) {
  const configured = resolveWsURL(resolvedWsUrl() || import.meta.env.VITE_WS_URL)
  // 去掉末尾 /ws 后缀，再拼任务专属路径
  const base = configured.endsWith('/ws') ? configured.slice(0, -3) : configured
  return `${base}/ws/backtests/${taskNo}`
}

/** 构造信号专用 WebSocket 地址（独立于通用 wsClient） */
export function signalWsUrl() {
  const configured = resolveWsURL(resolvedWsUrl() || import.meta.env.VITE_WS_URL)
  const base = configured.endsWith('/ws') ? configured.slice(0, -3) : configured
  return `${base}/ws/signals`
}
