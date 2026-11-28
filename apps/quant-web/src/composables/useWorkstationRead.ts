import { onMounted, onScopeDispose, shallowRef } from 'vue'

/** Each source retains its own loading and failure state. Refresh abandons older reads. */
export function useWorkstationRead<T>(read: (signal: AbortSignal) => Promise<T>) {
  const value = shallowRef<T>()
  const state = shallowRef<'loading' | 'ready' | 'error'>('loading')
  let controller: AbortController | undefined
  async function refresh() {
    controller?.abort()
    const active = new AbortController()
    controller = active
    value.value = undefined
    state.value = 'loading'
    try {
      const result = await read(active.signal)
      if (active.signal.aborted) return
      value.value = result
      state.value = 'ready'
    } catch {
      if (!active.signal.aborted) state.value = 'error'
    }
  }
  onMounted(refresh)
  onScopeDispose(() => controller?.abort())
  return { value, state, refresh }
}
