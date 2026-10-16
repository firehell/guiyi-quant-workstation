/** One browser foreground budget; queued navigation requests remain cancellable. */
export type ReadPriority = 0 | 1 | 2 | 3
export const READ_PRIORITY = {
  foreground: 0,
  selectedAuxiliary: 1,
  visibleDetail: 2,
  history: 3,
} as const satisfies Record<string, ReadPriority>

export function createReadAdmission(limit: number) {
  let active = 0
  const waiting: Array<{ next: () => void; priority: ReadPriority; sequence: number }> = []
  let sequence = 0
  const nextWaiting = () => {
    if (!waiting.length) return undefined
    const selected = waiting.reduce((best, item) => item.priority < best.priority
      || (item.priority === best.priority && item.sequence < best.sequence) ? item : best)
    waiting.splice(waiting.indexOf(selected), 1)
    return selected.next
  }
  return async (signal?: AbortSignal, priority: ReadPriority = READ_PRIORITY.visibleDetail): Promise<() => void> => {
    if (signal?.aborted) throw new DOMException('Aborted', 'AbortError')
    if (active >= limit) await new Promise<void>((resolve, reject) => {
      const cleanup = () => signal?.removeEventListener('abort', abort)
      const next = () => { cleanup(); resolve() }
      const item = { next, priority, sequence: sequence++ }
      const abort = () => { const index = waiting.indexOf(item); if (index >= 0) waiting.splice(index, 1); cleanup(); reject(new DOMException('Aborted', 'AbortError')) }
      waiting.push(item); signal?.addEventListener('abort', abort, { once: true })
      if (signal?.aborted) abort()
    })
    else active++
    let released = false
    const release = () => { if (released) return; released = true; const next = nextWaiting(); if (next) next(); else active-- }
    if (signal?.aborted) { release(); throw new DOMException('Aborted', 'AbortError') }
    return release
  }
}
