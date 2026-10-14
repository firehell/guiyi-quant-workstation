/** Disposable display snapshots, never Runtime/account authority. */
export interface HomeSnapshot<T = unknown> { key: string; savedAt: number; value: T; bytes: number }
export interface HomeSnapshotStorage { read(): Promise<unknown[]>; write(values: HomeSnapshot[]): Promise<void> }
export function indexedHomeStorage(name: string, factory: IDBFactory | undefined = globalThis.indexedDB): HomeSnapshotStorage {
  let database: Promise<IDBDatabase> | null = null
  const open = () => database ??= new Promise((resolve, reject) => {
    if (!factory) { reject(new Error('IDB_UNAVAILABLE')); return }
    const request = factory.open(name, 1)
    request.onupgradeneeded = () => request.result.createObjectStore('snapshots', { keyPath: 'key' })
    request.onsuccess = () => { request.result.onversionchange = () => request.result.close(); resolve(request.result) }
    request.onerror = () => reject(new Error('IDB_UNAVAILABLE'))
    request.onblocked = () => reject(new Error('IDB_BLOCKED'))
  })
  return {
    async read() { const db = await open(); return new Promise((resolve, reject) => {
      const transaction = db.transaction('snapshots', 'readonly'), request = transaction.objectStore('snapshots').getAll()
      request.onsuccess = () => resolve(request.result)
      transaction.onerror = () => reject(new Error('IDB_READ_FAILED'))
      transaction.onabort = () => reject(new Error('IDB_READ_FAILED'))
    }) },
    async write(values) { const db = await open(); await new Promise<void>((resolve, reject) => {
      const transaction = db.transaction('snapshots', 'readwrite'), store = transaction.objectStore('snapshots')
      store.clear(); for (const value of values) store.put(value)
      transaction.oncomplete = () => resolve()
      transaction.onerror = () => reject(new Error('IDB_WRITE_FAILED'))
      transaction.onabort = () => reject(new Error('IDB_WRITE_FAILED'))
    }) },
  }
}
export function createHomeSnapshotCache(storage: HomeSnapshotStorage, options: { now?: () => number; maxProducts?: number; maxBytes?: number; maxAgeMs?: number; storageTimeoutMs?: number } = {}) {
  const now = options.now ?? Date.now, maxProducts = options.maxProducts ?? 60, maxBytes = options.maxBytes ?? 10 * 1024 * 1024, maxAge = options.maxAgeMs ?? 7 * 86400_000
  const deadline = async <T>(operation: Promise<T>): Promise<T> => {
    let timer: ReturnType<typeof setTimeout> | undefined
    try {
      return await Promise.race([operation, new Promise<never>((_resolve, reject) => {
        timer = setTimeout(() => reject(new Error('HOME_STORAGE_TIMEOUT')), options.storageTimeoutMs ?? 150)
      })])
    } finally { if (timer) clearTimeout(timer) }
  }
  const entries = new Map<string, HomeSnapshot>()
  let enabled = true, restored = false, pending: Promise<void> | null = null, writing = Promise.resolve()
  // Include the persisted envelope and conservatively budget the byte-count field.
  const size = (key: string, value: unknown, savedAt = now()) => new TextEncoder().encode(JSON.stringify({ key, value, savedAt, bytes: 99999999 })).byteLength
  const prune = () => {
    for (const [key, value] of entries) if (value.savedAt > now() || now() - value.savedAt > maxAge) entries.delete(key)
    const oldest = () => [...entries.values()].sort((a, b) => a.savedAt - b.savedAt)
    while ([...entries.keys()].filter(key => key.startsWith('card:')).length > maxProducts) entries.delete(oldest().find(value => value.key.startsWith('card:'))!.key)
    while ([...entries.values()].reduce((sum, value) => sum + value.bytes, 0) > maxBytes) entries.delete(oldest()[0]!.key)
  }
  const persist = () => { writing = writing.then(async () => { if (enabled) try { await deadline(storage.write([...entries.values()])) } catch { enabled = false } }); return writing }
  async function restore() {
    if (restored) return
    if (pending) return pending
    pending = (async () => {
      try {
        for (const item of await deadline(storage.read())) {
          const value = item as HomeSnapshot
          if (!value || typeof value.key !== 'string' || !/^(overview|directory|card:[a-z0-9]+)$/.test(value.key) || !Number.isFinite(value.savedAt) || value.value == null) continue
          try { const bytes = size(value.key, value.value, value.savedAt); if (bytes <= maxBytes && !entries.has(value.key)) entries.set(value.key, { ...value, bytes }) } catch {}
        }
        prune(); void persist()
      } catch { enabled = false }
      restored = true
    })()
    return pending
  }
  return {
    restore,
    peek<T>(key: string): HomeSnapshot<T> | undefined { prune(); const value = entries.get(key); return value ? structuredClone(value) as HomeSnapshot<T> : undefined },
    async put(key: string, value: unknown) { await restore(); const bytes = size(key, value); if (bytes > maxBytes) return; entries.set(key, { key, value: structuredClone(value), savedAt: now(), bytes }); prune(); await persist() },
    async discard(key: string) { entries.delete(key); await persist() },
    stats() { prune(); return { entries: entries.size, bytes: [...entries.values()].reduce((sum, value) => sum + value.bytes, 0), persistent: enabled } },
  }
}
export type HomeSnapshotCache = ReturnType<typeof createHomeSnapshotCache>
