export type HomeReadFailure = 'transport' | 'protocol' | 'access'
export function homeReadFailure(error: unknown): HomeReadFailure {
  const value = error as { response?: { status?: number }; message?: string }
  if (value?.response?.status === 401 || value?.response?.status === 403) return 'access'
  if (/INVALID_HOME_|HOME_(304_WITHOUT|UNEXPECTED)/.test(value?.message ?? '')) return 'protocol'
  return 'transport'
}

/** One request per page, with no finite polling horizon. Invalidated responses never publish. */
export function createHomeProjectionReadLoop<T>(options: {
  read: (signal: AbortSignal) => Promise<T>
  accept: (value: T) => void
  failed: (kind: HomeReadFailure) => void
  pending: (value: T) => boolean
  schedule?: (callback: () => void, delay: number) => ReturnType<typeof setTimeout>
  cancel?: (timer: ReturnType<typeof setTimeout>) => void
}) {
  const schedule = options.schedule ?? setTimeout, cancel = options.cancel ?? clearTimeout
  let timer: ReturnType<typeof setTimeout> | undefined
  let controller: AbortController | undefined
  let active = false, disposed = false, inFlight = false, immediate = false, accessBlocked = false
  let generation = 0, failures = 0
  function clear() { if (timer !== undefined) cancel(timer); timer = undefined }
  function later(delay: number) { clear(); if (active && !disposed && !accessBlocked) timer = schedule(() => { timer = undefined; void run() }, delay) }
  async function run() {
    if (!active || disposed || accessBlocked) return
    if (inFlight) { immediate = true; return }
    inFlight = true; immediate = false
    const owner = ++generation, request = new AbortController()
    controller = request
    let delay: number | undefined
    try {
      const value = await options.read(request.signal)
      if (request.signal.aborted || owner !== generation || !active || disposed) return
      options.accept(value); failures = 0
      delay = options.pending(value) ? 10_000 : 60_000
    } catch (error) {
      if (request.signal.aborted || owner !== generation || !active || disposed) return
      const kind = homeReadFailure(error)
      options.failed(kind)
      accessBlocked = kind === 'access'
      delay = kind === 'transport' ? [2_000, 5_000, 15_000, 30_000, 60_000][Math.min(failures++, 4)]! : 60_000
    } finally {
      inFlight = false
      if (controller === request) controller = undefined
      if (immediate && active && !disposed && !accessBlocked) { immediate = false; void run() }
      else if (delay !== undefined) later(delay)
    }
  }
  function refresh() {
    if (!active || disposed) return
    clear(); ++generation; controller?.abort(); immediate = true
    // An explicit refresh may retry access, but visibility/online changes may not loop authentication.
    accessBlocked = false
    void run()
  }
  return {
    refresh,
    wake() { if (active && !accessBlocked) { clear(); void run() } },
    setActive(value: boolean) {
      if (active === value || disposed) return
      active = value; clear(); ++generation; controller?.abort()
      if (active && !accessBlocked) { immediate = true; void run() }
    },
    dispose() { disposed = true; active = false; immediate = false; ++generation; clear(); controller?.abort() },
  }
}
