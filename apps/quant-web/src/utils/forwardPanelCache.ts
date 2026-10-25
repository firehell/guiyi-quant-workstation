/** Short-lived, bounded successes only. Aborting one view cannot cancel another. */
export function createForwardPanelCache<T>(ttl = 15_000, capacity = 20, now = Date.now) {
  const saved = new Map<string, { value: T; expires: number }>()
  const pending = new Map<string, { promise: Promise<T>; controller: AbortController; users: number }>()
  async function load(key: string, read: (signal: AbortSignal) => Promise<T>, signal: AbortSignal, force = false): Promise<T> {
    if (signal.aborted) throw new DOMException('Aborted', 'AbortError')
    if (force) saved.delete(key)
    const hit = saved.get(key)
    if (hit && hit.expires > now()) return structuredClone(hit.value)
    saved.delete(key)
    let job = pending.get(key)
    if (!job || job.controller.signal.aborted) {
      const controller = new AbortController()
      const current = { controller, users: 0, promise: null as unknown as Promise<T> }
      current.promise = Promise.resolve().then(() => read(controller.signal)).then(value => {
        if (!controller.signal.aborted) {
          saved.set(key, { value: structuredClone(value), expires: now() + ttl })
          while (saved.size > capacity) saved.delete(saved.keys().next().value!)
        }
        return value
      }).finally(() => { if (pending.get(key) === current) pending.delete(key) })
      job = current; pending.set(key, current)
    }
    const active = job
    active.users++
    return new Promise<T>((resolve, reject) => {
      let ended = false
      const finish = () => {
        if (ended) return false
        ended = true; signal.removeEventListener('abort', abort); active.users--
        if (!active.users) active.controller.abort()
        return true
      }
      const abort = () => { if (finish()) reject(new DOMException('Aborted', 'AbortError')) }
      signal.addEventListener('abort', abort, { once: true })
      active.promise.then(value => { if (finish()) resolve(structuredClone(value)) }, reason => { if (finish()) reject(reason) })
    })
  }
  return { load }
}
