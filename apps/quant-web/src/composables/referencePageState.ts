// Shared snapshot and cursor contract for the unified reader and its existing page adapters.
export function createReferencePageState<T>(key: (item: T) => string, maxItems = 10_000, allowIdenticalOverlap = false) {
  let identity: string | null = null
  let cursor: string | null = null
  let items: T[] = []

  function reset() {
    identity = null
    cursor = null
    items = []
  }

  function first(snapshotIdentity: string, pageItems: readonly T[], nextCursor: string | null) {
    reset()
    if (!snapshotIdentity || new Set(pageItems.map(key)).size !== pageItems.length) throw new Error('SNAPSHOT_CONFLICT')
    identity = snapshotIdentity
    items = [...pageItems]
    cursor = nextCursor
    return items
  }

  function append(snapshotIdentity: string, requestedCursor: string, pageItems: readonly T[], nextCursor: string | null) {
    if (identity !== snapshotIdentity || cursor === null || cursor !== requestedCursor) throw new Error('SNAPSHOT_CONFLICT')
    const seen = new Map(items.map(item => [key(item), item]))
    const appended: T[] = []
    for (const item of pageItems) {
      const prior = seen.get(key(item))
      if (prior !== undefined) {
        if (!allowIdenticalOverlap || JSON.stringify(prior) !== JSON.stringify(item)) throw new Error('SNAPSHOT_CONFLICT')
        continue
      }
      seen.set(key(item), item)
      appended.push(item)
    }
    const combined = [...items, ...appended]
    items = combined.slice(0, maxItems)
    cursor = combined.length >= maxItems ? null : nextCursor
    return items
  }

  return { first, append, reset, get cursor() { return cursor }, get items() { return items } }
}
