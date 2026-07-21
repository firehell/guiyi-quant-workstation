/**
 * WebSocket 客户端 — 支持自动重连与按事件类型分发消息
 */
export class WsClient {
  private ws: WebSocket | null = null
  private url: string
  private reconnectAttempts = 0
  private maxReconnectAttempts = 5
  private reconnectInterval = 3000
  private listeners = new Map<string, Set<(data: unknown) => void>>()
  /** 主动 disconnect 时置 false，阻止 onclose 触发重连 */
  private shouldReconnect = true

  constructor(url: string) {
    this.url = url
  }

  /** 建立连接；成功后重置重连计数 */
  connect() {
    this.shouldReconnect = true
    this.ws = new WebSocket(this.url)

    this.ws.onopen = () => {
      console.log('[WS] Connected')
      this.reconnectAttempts = 0
      this.emit('open', null)
    }

    this.ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data)
        // 服务端消息格式：{ type, data }；无 type 时回退为 'message'
        this.emit(msg.type || 'message', msg.data ?? msg)
      } catch {
        console.warn('[WS] Failed to parse message:', event.data)
      }
    }

    this.ws.onerror = (error) => {
      console.error('[WS] Error:', error)
      this.emit('error', error)
    }

    this.ws.onclose = () => {
      console.log('[WS] Closed')
      this.emit('close', null)
      // 非主动断开且未达上限时，延迟重连
      if (this.shouldReconnect && this.reconnectAttempts < this.maxReconnectAttempts) {
        this.reconnectAttempts++
        console.log(`[WS] Reconnecting (${this.reconnectAttempts}/${this.maxReconnectAttempts})...`)
        setTimeout(() => this.connect(), this.reconnectInterval)
      }
    }
  }

  /** 发送 JSON 帧，连接未 OPEN 时静默丢弃 */
  send(type: string, data: unknown) {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ type, data }))
    }
  }

  /** 注册事件监听，同一事件可绑定多个回调 */
  on(event: string, callback: (data: unknown) => void) {
    if (!this.listeners.has(event)) {
      this.listeners.set(event, new Set())
    }
    this.listeners.get(event)!.add(callback)
  }

  /** 移除已注册的事件监听 */
  off(event: string, callback: (data: unknown) => void) {
    this.listeners.get(event)?.delete(callback)
  }

  /** 主动断开并禁止自动重连 */
  disconnect() {
    this.shouldReconnect = false
    this.ws?.close()
    this.ws = null
  }

  private emit(event: string, data: unknown) {
    this.listeners.get(event)?.forEach((cb) => cb(data))
  }
}
