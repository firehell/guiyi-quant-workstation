/** Read-only page resources. Account facts and order commands never belong here. */
export function createSessionResources(options: { maxEntries?: number; maxBytes?: number; ttl?: number; now?: () => number } = {}) {
  const maxEntries = options.maxEntries ?? 120, maxBytes = options.maxBytes ?? 32 * 1024 * 1024
  const ttl = options.ttl ?? 5 * 60_000, now = options.now ?? Date.now
  const entries = new Map<string, { value: unknown; expires: number; bytes: number; identity: string }>()
  const pending = new Map<string, { controller: AbortController; promise: Promise<unknown> }>()
  let bytes = 0
  function remove(key: string) { const entry = entries.get(key); if (entry) bytes -= entry.bytes; entries.delete(key) }
  function prune() { for (const [key, entry] of entries) if (entry.expires <= now()) remove(key) }
  function put<T>(key: string, value: T, identity: string) {
    prune(); remove(key)
    const size = new TextEncoder().encode(JSON.stringify(value) + identity + key).byteLength
    if (size > maxBytes) return
    while (entries.size >= maxEntries || bytes + size > maxBytes) remove(entries.keys().next().value!)
    entries.set(key, { value: structuredClone(value), identity, expires: now() + ttl, bytes: size }); bytes += size
  }
  function peek<T>(key: string): T | undefined {
    prune(); const entry = entries.get(key)
    if (!entry) return undefined
    entries.delete(key); entries.set(key, entry)
    return structuredClone(entry.value) as T
  }
  function invalidate(prefix = '') {
    for (const key of entries.keys()) if (key.startsWith(prefix)) remove(key)
    for (const [key, item] of pending) if (key.startsWith(prefix)) { pending.delete(key); item.controller.abort() }
  }
  function find<T>(select: (value: unknown) => T | undefined): T | undefined {
    prune()
    for (const [key, entry] of entries) {
      const value = select(entry.value)
      if (value !== undefined) { entries.delete(key); entries.set(key, entry); return structuredClone(value) }
    }
    return undefined
  }
  async function load<T>(key: string, fetch: (signal: AbortSignal) => Promise<T>, identity: (value: T) => string, signal?: AbortSignal): Promise<T> {
    if (signal?.aborted) throw new DOMException('Aborted', 'AbortError')
    let promise: Promise<T>
    const cached = peek<T>(key)
    if (cached !== undefined) return cached
    const existing = pending.get(key)
    if (existing) promise = existing.promise as Promise<T>
    else {
      if (pending.size >= maxEntries) throw new Error('NEWOW_RESOURCE_BUSY')
      const controller = new AbortController()
      const item = { controller, promise: Promise.resolve() as Promise<unknown> }
      promise = Promise.resolve().then(() => fetch(controller.signal)).then(value => {
        // Invalidation deletes the owner before aborting. Even a transport
        // ignoring cancellation cannot admit an obsolete result.
        if (pending.get(key) === item && !controller.signal.aborted) put(key, value, identity(value))
        return value
      }).finally(() => { if (pending.get(key) === item) pending.delete(key) })
      item.promise = promise; pending.set(key, item)
    }
    // A view owns its subscription, not the shared HTTP request. Navigation
    // detaches it; only authority/explicit refresh invalidates the owner.
    if (!signal) return structuredClone(await promise)
    return new Promise<T>((resolve, reject) => {
      const abort = () => { cleanup(); reject(new DOMException('Aborted', 'AbortError')) }
      const cleanup = () => signal.removeEventListener('abort', abort)
      signal.addEventListener('abort', abort, { once: true })
      promise.then(value => { cleanup(); if (!signal.aborted) resolve(structuredClone(value)) }, error => { cleanup(); reject(error) })
    })
  }
  return { load, put, peek, find, invalidate, stats: () => { prune(); return { entries: entries.size, pending: pending.size, bytes } } }
}

export const newowSessionResources = createSessionResources()

export function invalidateNewowProduct(product: string) {
  newowSessionResources.invalidate(`newow:${product}:`)
  newowSessionResources.invalidate(`home:${product}:`)
}

/** Bounded transport admission, including product-only conflict recovery. */
export function createReadQueue(limit: number) {
  let active = 0
  const waiting: Array<() => void> = []
  return async function run<T>(operation: () => Promise<T>, signal: AbortSignal): Promise<T> {
    if (active >= limit) await new Promise<void>((resolve, reject) => {
      const next = () => { cleanup(); resolve() }
      const abort = () => { const index = waiting.indexOf(next); if (index >= 0) waiting.splice(index, 1); cleanup(); reject(new DOMException('Aborted', 'AbortError')) }
      const cleanup = () => signal.removeEventListener('abort', abort)
      waiting.push(next); signal.addEventListener('abort', abort, { once: true })
      if (signal.aborted) abort()
    })
    else active++
    try {
      if (signal.aborted) throw new DOMException('Aborted', 'AbortError')
      return await operation()
    } finally { const next = waiting.shift(); if (next) next(); else active-- }
  }
}

/** Full response ownership, including versions/proofs; request aliases are TTL bounded. */
export function newowResourceIdentity(value: unknown): string {
  const response = value as { meta?: unknown; schema_version?: string; items?: Array<{ product: string; strategies?: unknown }> }
  if (response.meta) return JSON.stringify(response.meta)
  if (response.schema_version === 'newow_home_cards_v2') {
    return JSON.stringify(response.items?.map(item => [item.product, item.strategies]))
  }
  return JSON.stringify(value)
}
