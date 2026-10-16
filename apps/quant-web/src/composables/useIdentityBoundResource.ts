import { ref, shallowRef } from 'vue'

/** Read-only facts: invalidate the value before loading a different identity. */
export function useIdentityBoundResource<Identity, Wire, Value>(options: {
  key: (identity: Identity) => string
  load: (identity: Identity, signal: AbortSignal) => Promise<Wire>
  project: (wire: Wire, identity: Identity) => Value
}) {
  const value = shallowRef<Value | null>(null)
  const unavailable = ref(false)
  let activeKey: string | null = null
  let generation = 0
  let disposed = false
  let controller = new AbortController()

  async function refresh(identity: Identity): Promise<void> {
    if (disposed) return
    controller.abort(); controller = new AbortController()
    const signal = controller.signal
    const current = ++generation
    const nextKey = options.key(identity)
    if (nextKey !== activeKey) {
      activeKey = nextKey
      value.value = null
      unavailable.value = true
    }
    try {
      const wire = await options.load(identity, signal)
      if (disposed || current !== generation) return
      value.value = options.project(wire, identity)
      unavailable.value = false
    } catch {
      if (disposed || current !== generation) return
      value.value = null
      unavailable.value = true
    }
  }

  function dispose() {
    disposed = true
    controller.abort()
    generation += 1
    activeKey = null
    value.value = null
    unavailable.value = true
  }

  return { value, unavailable, refresh, dispose }
}
