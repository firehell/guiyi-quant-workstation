/** One browser foreground budget; queued navigation requests remain cancellable. */
export function createReadAdmission(limit: number) {
  let active = 0
  const waiting: Array<() => void> = []
  return async (signal?: AbortSignal): Promise<() => void> => {
    if (signal?.aborted) throw new DOMException('Aborted', 'AbortError')
    if (active >= limit) await new Promise<void>((resolve, reject) => {
      const cleanup = () => signal?.removeEventListener('abort', abort)
      const next = () => { cleanup(); resolve() }
      const abort = () => { const index = waiting.indexOf(next); if (index >= 0) waiting.splice(index, 1); cleanup(); reject(new DOMException('Aborted', 'AbortError')) }
      waiting.push(next); signal?.addEventListener('abort', abort, { once: true })
      if (signal?.aborted) abort()
    })
    else active++
    let released = false
    const release = () => { if (released) return; released = true; const next = waiting.shift(); if (next) next(); else active-- }
    if (signal?.aborted) { release(); throw new DOMException('Aborted', 'AbortError') }
    return release
  }
}
