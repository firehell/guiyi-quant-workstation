export const RUNTIME_PULSE_STALE_MS = 60_000

export interface RuntimePulseRefreshState {
  visible: boolean
  inFlight: boolean
  now: number
  loadedAt: number
  staleAfterMs?: number
}

/** System Pulse 只在页面可见、无请求进行中且快照已过期时刷新。 */
export function shouldRefreshRuntimePulse(state: RuntimePulseRefreshState): boolean {
  const staleAfterMs = state.staleAfterMs ?? RUNTIME_PULSE_STALE_MS
  return state.visible && !state.inFlight && state.now - state.loadedAt >= staleAfterMs
}
