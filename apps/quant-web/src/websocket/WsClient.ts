/**
 * WebSocket 客户端 — 支持自动重连
 */
export class WsClient {
  private ws: WebSocket | null = null
  private url: string
  private reconnectAttempts = 0
  private maxReconnectAttempts = 5
  private reconnectInterval = 3000
  private listeners = new Map<string, Set<(data: unknown) => void>>()
  private shouldReconnect = true

  constructor(url: string) {
    this.url = url
  }

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
      if (this.shouldReconnect && this.reconnectAttempts < this.maxReconnectAttempts) {
        this.reconnectAttempts++
        console.log(`[WS] Reconnecting (${this.reconnectAttempts}/${this.maxReconnectAttempts})...`)
        setTimeout(() => this.connect(), this.reconnectInterval)
      }
    }
  }

  send(type: string, data: unknown) {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ type, data }))
    }
  }

  on(event: string, callback: (data: unknown) => void) {
    if (!this.listeners.has(event)) {
      this.listeners.set(event, new Set())
    }
    this.listeners.get(event)!.add(callback)
  }

  off(event: string, callback: (data: unknown) => void) {
    this.listeners.get(event)?.delete(callback)
  }

  disconnect() {
    this.shouldReconnect = false
    this.ws?.close()
    this.ws = null
  }

  private emit(event: string, data: unknown) {
    this.listeners.get(event)?.forEach((cb) => cb(data))
  }
}
