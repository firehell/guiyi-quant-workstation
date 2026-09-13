import { shallowRef } from 'vue'
import type { MarketHomeLiveItem } from '../types/market.ts'
import { normalizeMarketHomeLiveFrame } from '../utils/marketHomeLive.ts'
import { resolveWsURL } from '../utils/network.ts'

interface MarketHomeSocket { onmessage: ((event: { data: string }) => void) | null; onclose: (() => void) | null; close: () => void }
interface Dependencies {
  createWebSocket?: (url: string) => MarketHomeSocket
  resolveWsURL?: () => string
  scheduleReconnect?: (callback: () => void, delayMs: number) => unknown
  clearReconnect?: (handle: unknown) => void
  onAuthorityChanged?: () => void
}
const MAX_RECONNECTS = 6

export function useMarketHomeLive(dependencies: Dependencies = {}) {
  const items = shallowRef(new Map<string, MarketHomeLiveItem>())
  const connection = shallowRef<'idle' | 'connecting' | 'connected' | 'stale' | 'unavailable'>('idle')
  const stale = shallowRef(false)
  const observedAt = shallowRef<string | null>(null)
  const createWebSocket = dependencies.createWebSocket ?? ((url) => new WebSocket(url) as unknown as MarketHomeSocket)
  const websocketUrl = dependencies.resolveWsURL ?? defaultWsUrl
  const scheduleReconnect = dependencies.scheduleReconnect ?? ((callback, delay) => setTimeout(callback, delay))
  const clearReconnect = dependencies.clearReconnect ?? ((handle) => clearTimeout(handle as ReturnType<typeof setTimeout>))
  let generation = 0
  let socket: MarketHomeSocket | null = null
  let reconnectHandle: unknown = null
  let reconnects = 0
  let disposed = false
  let hasSnapshot = false
  let listening = false
  let lastObservedAt = Number.NEGATIVE_INFINITY

  function onVisibilityChange() {
    if (document.visibilityState === 'visible') {
      if (!socket && reconnectHandle === null) restart()
      return
    }
    generation += 1
    if (reconnectHandle !== null) { clearReconnect(reconnectHandle); reconnectHandle = null }
    const previous = socket; socket = null; previous?.close()
    stale.value = items.value.size > 0
    connection.value = items.value.size ? 'stale' : 'idle'
  }

  function open(current: number) {
    if (disposed || current !== generation) return
    connection.value = items.value.size ? 'stale' : 'connecting'
    const next = createWebSocket(websocketUrl())
    socket = next
    next.onmessage = (event) => {
      if (disposed || current !== generation || socket !== next) return
      try {
        const frame = normalizeMarketHomeLiveFrame(JSON.parse(event.data))
        const frameTime = Date.parse(frame.observedAt)
        if (frameTime < lastObservedAt) return
        if (frame.type === 'unavailable') { lastObservedAt = frameTime; observedAt.value = frame.observedAt; stale.value = items.value.size > 0; connection.value = 'unavailable'; return }
        if (frame.type === 'snapshot' || frame.type === 'reset') {
          items.value = new Map(frame.items.map((item) => [item.symbol, item]))
          hasSnapshot = true
          if (frame.type === 'reset') dependencies.onAuthorityChanged?.()
        } else {
          if (!hasSnapshot) return
          const previous = items.value.get(frame.item.symbol)
          if (!previous || (
            previous.physicalContract !== frame.item.physicalContract
            || previous.tradingDay !== frame.item.tradingDay
            || (previous.barEnd !== null && frame.item.barEnd !== null && Date.parse(frame.item.barEnd) < Date.parse(previous.barEnd))
          )) return
          items.value = new Map(items.value).set(frame.item.symbol, frame.item)
        }
        lastObservedAt = frameTime
        observedAt.value = frame.observedAt
        stale.value = false
        connection.value = 'connected'
        reconnects = 0
      } catch {
        stale.value = items.value.size > 0
        connection.value = 'unavailable'
      }
    }
    next.onclose = () => {
      if (disposed || current !== generation || socket !== next) return
      socket = null
      stale.value = items.value.size > 0
      connection.value = items.value.size ? 'stale' : 'unavailable'
      if (reconnects >= MAX_RECONNECTS) { connection.value = 'unavailable'; return }
      const delay = Math.min(10_000 * (2 ** reconnects++), 60_000)
      reconnectHandle = scheduleReconnect(() => { reconnectHandle = null; open(current) }, delay)
    }
  }

  function start() {
    if (socket || reconnectHandle !== null || disposed) return
    if (!listening && typeof document !== 'undefined') { document.addEventListener('visibilitychange', onVisibilityChange); listening = true }
    open(++generation)
  }
  function restart() {
    if (disposed) return
    generation += 1
    if (reconnectHandle !== null) { clearReconnect(reconnectHandle); reconnectHandle = null }
    const previous = socket; socket = null; previous?.close()
    reconnects = 0
    hasSnapshot = false
    lastObservedAt = Number.NEGATIVE_INFINITY
    open(generation)
  }
  function dispose() {
    disposed = true; generation += 1
    if (listening && typeof document !== 'undefined') { document.removeEventListener('visibilitychange', onVisibilityChange); listening = false }
    if (reconnectHandle !== null) { clearReconnect(reconnectHandle); reconnectHandle = null }
    const previous = socket; socket = null; previous?.close()
  }
  return { items, connection, stale, observedAt, start, restart, dispose }
}

function defaultWsUrl(): string {
  const base = resolveWsURL(import.meta.env?.VITE_MARKET_WS_URL)
  const url = new URL(base, base.includes('://') ? undefined : 'ws://market.local')
  url.pathname = '/api/v1/market/research/home-live/ws'
  url.search = ''
  return base.includes('://') ? url.toString() : `${url.pathname}${url.search}`
}
