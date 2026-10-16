// Shared snapshot and cursor contract for the unified reader and its existing page adapters.
export function createReferencePageState<T>(key: (item: T) => string, maxItems = 10_000, allowIdenticalOverlap = false) {
  let identity: string | null = null
  let cursor: string | null = null
  let items: T[] = []
  let capped = false

  function reset() {
    capped = false
    identity = null
    cursor = null
    items = []
  }

  function first(snapshotIdentity: string, pageItems: readonly T[], nextCursor: string | null) {
    reset()
    if (!snapshotIdentity || new Set(pageItems.map(key)).size !== pageItems.length) throw new Error('SNAPSHOT_CONFLICT')
    identity = snapshotIdentity
    capped = pageItems.length > maxItems || pageItems.length === maxItems && nextCursor !== null
    items = pageItems.slice(0, maxItems)
    cursor = nextCursor
    return items
  }

  function append(snapshotIdentity: string, requestedCursor: string, pageItems: readonly T[], nextCursor: string | null) {
    if (identity !== snapshotIdentity || cursor === null || cursor !== requestedCursor) throw new Error('SNAPSHOT_CONFLICT')
    if (capped) throw new Error('PRESENTATION_BUDGET_EXCEEDED')
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
    capped = combined.length > maxItems || combined.length === maxItems && nextCursor !== null
    cursor = nextCursor
    return items
  }

  return { first, append, reset, get cursor() { return cursor }, get items() { return items }, get capped() { return capped } }
}
