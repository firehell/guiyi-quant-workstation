/** Disposable detail prices. Each operation reads the current compact LRU index. */
export interface DetailPriceEntry { key: string; savedAt: number; value: unknown; bytes: number }
interface EntryIndex { key: string; savedAt: number; usedAt: number; bytes: number }
export interface PriceIndex { key: '__meta__'; version: 1; entries: EntryIndex[] }
export interface DetailPriceChange<T> {
  result: T
  index?: PriceIndex
  entry?: DetailPriceEntry
  removals?: string[]
}
export interface DetailPriceStorage {
  transact<T>(key: string, change: (index: unknown, entry: unknown) => DetailPriceChange<T>, signal?: AbortSignal): Promise<T>
}

const META_KEY = '__meta__'
const MAX_ENTRIES = 512
const DEFAULT_BYTES = 32 * 1024 * 1024
const DEFAULT_AGE = 7 * 86400_000

export function indexedDetailPriceStorage(name: string, factory: IDBFactory | undefined = globalThis.indexedDB): DetailPriceStorage {
  let database: Promise<IDBDatabase> | null = null
  const open = () => database ??= new Promise((resolve, reject) => {
    if (!factory) { reject(new Error('IDB_UNAVAILABLE')); return }
    // V1 has no index. Drop only this disposable price store once at upgrade.
    const request = factory.open(name, 2)
    let blocked = false
    request.onupgradeneeded = () => {
      if (request.result.objectStoreNames.contains('snapshots')) request.result.deleteObjectStore('snapshots')
      request.result.createObjectStore('snapshots', { keyPath: 'key' })
    }
    request.onsuccess = () => {
      if (blocked) { request.result.close(); return }
      request.result.onversionchange = () => request.result.close()
      resolve(request.result)
    }
    request.onerror = () => { if (!blocked) reject(new Error('IDB_UNAVAILABLE')) }
    request.onblocked = () => { blocked = true; reject(new Error('IDB_BLOCKED')) }
  })
  return {
    async transact<T>(key: string, change: (index: unknown, entry: unknown) => DetailPriceChange<T>, signal?: AbortSignal): Promise<T> {
      const db = await open()
      if (signal?.aborted) throw new Error('PRICE_STORAGE_CANCELLED')
      return new Promise<T>((resolve, reject) => {
        const transaction = db.transaction('snapshots', 'readwrite')
        const abort = () => { try { transaction.abort() } catch { /* already settled */ } }
        signal?.addEventListener('abort', abort, { once: true })
        const cleanup = () => signal?.removeEventListener('abort', abort)
        const store = transaction.objectStore('snapshots')
        const metaRead = store.get(META_KEY), entryRead = store.get(key)
        let metaReady = false, entryReady = false, result!: T
        const apply = () => {
          if (!metaReady || !entryReady) return
          try {
            if (signal?.aborted) { transaction.abort(); return }
            const mutation = change(metaRead.result, entryRead.result)
            result = mutation.result
            for (const removed of mutation.removals ?? []) store.delete(removed)
            if (mutation.entry) store.put(mutation.entry)
            if (mutation.index) store.put(mutation.index)
          } catch { transaction.abort() }
        }
        metaRead.onsuccess = () => { metaReady = true; apply() }
        entryRead.onsuccess = () => { entryReady = true; apply() }
        transaction.oncomplete = () => { cleanup(); resolve(result) }
        transaction.onerror = transaction.onabort = () => { cleanup(); reject(new Error('IDB_PRICE_TRANSACTION_FAILED')) }
      })
    },
  }
}

export function createDetailPriceDiskCache(storage: DetailPriceStorage, options: {
  now?: () => number; maxBytes?: number; maxAgeMs?: number; timeoutMs?: number
} = {}) {
  const now = options.now ?? Date.now
  const maxBytes = options.maxBytes ?? DEFAULT_BYTES, maxAge = options.maxAgeMs ?? DEFAULT_AGE
  let enabled = true, lastEntries = 0, lastBytes = 0
  const size = (key: string, value: unknown, savedAt: number) =>
    new TextEncoder().encode(JSON.stringify({ key, savedAt, value, bytes: 99999999 })).byteLength
  const indexSize = (value: PriceIndex) => new TextEncoder().encode(JSON.stringify(value)).byteLength
  async function deadline<T>(operation: (signal: AbortSignal) => Promise<T>): Promise<T> {
    const controller = new AbortController()
    let timer: ReturnType<typeof setTimeout> | undefined
    try {
      return await Promise.race([operation(controller.signal), new Promise<never>((_resolve, reject) => {
        timer = setTimeout(() => { controller.abort(); reject(new Error('PRICE_STORAGE_TIMEOUT')) }, options.timeoutMs ?? 150)
      })])
    } finally { if (timer) clearTimeout(timer) }
  }
  function validIndex(value: unknown): value is PriceIndex {
    if (!value || typeof value !== 'object') return false
    const item = value as Partial<PriceIndex>
    return item.key === META_KEY && item.version === 1 && Array.isArray(item.entries)
      && item.entries.length <= MAX_ENTRIES && item.entries.every(entry =>
        entry && typeof entry.key === 'string' && entry.key.startsWith('price:')
        && Number.isFinite(entry.savedAt) && Number.isFinite(entry.usedAt) && entry.usedAt >= entry.savedAt
        && Number.isSafeInteger(entry.bytes) && entry.bytes > 0 && entry.bytes <= maxBytes)
      && new Set(item.entries.map(entry => entry.key)).size === item.entries.length
      && item.entries.reduce((total, entry) => total + entry.bytes, 0) + indexSize(item as PriceIndex) <= maxBytes
  }
  function readIndex(value: unknown): PriceIndex {
    if (value === undefined) return { key: META_KEY, version: 1, entries: [] }
    if (!validIndex(value)) throw new Error('PRICE_CACHE_INDEX_INVALID')
    return value
  }
  function prune(index: PriceIndex, current: number): string[] {
    const removals: string[] = []
    index.entries = index.entries.filter(item => {
      const expired = item.savedAt > current || current - item.savedAt >= maxAge
      if (expired) removals.push(item.key)
      return !expired
    })
    return removals
  }
  function rememberStats(index: PriceIndex) {
    lastEntries = index.entries.length
    lastBytes = index.entries.reduce((sum, item) => sum + item.bytes, 0) + indexSize(index)
  }
  return {
    async get<T>(key: string, validate: (value: unknown) => T): Promise<T | undefined> {
      if (!enabled) return
      try {
        return await deadline(signal => storage.transact(key, (storedIndex, storedEntry) => {
          if (signal.aborted || !enabled) throw new Error('PRICE_STORAGE_CANCELLED')
          const index = readIndex(storedIndex)
          const current = now(), removals = prune(index, current)
          const record = index.entries.find(item => item.key === key)
          if (!record) { rememberStats(index); return { result: undefined, ...(removals.length ? { index, removals } : {}) } }
          try {
            const entry = storedEntry as DetailPriceEntry | undefined
            if (!entry || entry.key !== key || entry.savedAt !== record.savedAt || entry.bytes !== record.bytes
              || size(key, entry.value, entry.savedAt) !== record.bytes) throw new Error('PRICE_CACHE_CORRUPT')
            const value = validate(entry.value)
            record.usedAt = current
            rememberStats(index)
            return { result: value, index, removals }
          } catch {
            index.entries = index.entries.filter(item => item.key !== key)
            rememberStats(index)
            return { result: undefined, index, removals: [...removals, key] }
          }
        }, signal))
      } catch { enabled = false; return }
    },
    async put(key: string, value: unknown): Promise<void> {
      if (!enabled || !key.startsWith('price:')) return
      let copy: unknown
      try { copy = structuredClone(value) } catch { return }
      const savedAt = now()
      try {
        await deadline(signal => storage.transact(key, storedIndex => {
          if (signal.aborted || !enabled) throw new Error('PRICE_STORAGE_CANCELLED')
          const index = readIndex(storedIndex)
          const current = now(), bytes = size(key, copy, savedAt)
          const removals = prune(index, current)
          if (bytes > maxBytes) { rememberStats(index); return { result: undefined, ...(removals.length ? { index, removals } : {}) } }
          index.entries = index.entries.filter(item => item.key !== key)
          index.entries.push({ key, savedAt, usedAt: current, bytes })
          let total = index.entries.reduce((sum, item) => sum + item.bytes, 0)
          while (index.entries.length && (index.entries.length > MAX_ENTRIES || total + indexSize(index) > maxBytes)) {
            const oldest = index.entries.reduce((a, b) => a.usedAt <= b.usedAt ? a : b)
            index.entries.splice(index.entries.indexOf(oldest), 1)
            total -= oldest.bytes
            removals.push(oldest.key)
          }
          rememberStats(index)
          return {
            result: undefined, index, removals,
            entry: index.entries.some(item => item.key === key) ? { key, savedAt, value: copy, bytes } : undefined,
          }
        }, signal))
      } catch { enabled = false }
    },
    stats: () => ({ entries: lastEntries, bytes: lastBytes, persistent: enabled }),
  }
}
