/** Admit visible rows in page order; never change authority or interpret facts. */
export function createHomeCardViewport(
  publish: (products: readonly string[], reset: boolean) => void,
  factory: ((callback: IntersectionObserverCallback) => Pick<IntersectionObserver, 'observe' | 'unobserve' | 'disconnect'>) | null = typeof IntersectionObserver === 'undefined' ? null : callback => new IntersectionObserver(callback, { rootMargin: '200px 0px' }),
) {
  let products: readonly string[] = []
  let admitted = new Set<string>()
  const targets = new Map<Element, string>()
  let generation = 0
  let disposed = false
  let pendingGeneration: number | null = null
  let lastPublished = ''
  const emit = (reset = false) => {
    const selected = products.filter(product => admitted.has(product))
    const key = JSON.stringify(selected)
    if (key !== lastPublished) { lastPublished = key; publish(selected, reset) }
  }
  const observer = factory?.(entries => {
    let changed = false
    for (const entry of entries) {
      const symbol = targets.get(entry.target)
      if (entry.isIntersecting && symbol && products.includes(symbol) && !admitted.has(symbol)) { admitted.add(symbol); changed = true }
    }
    if (!changed || pendingGeneration === generation || disposed) return
    const owner = generation
    pendingGeneration = owner
    queueMicrotask(() => { if (pendingGeneration === owner) pendingGeneration = null; if (!disposed && owner === generation) emit() })
  })
  return {
    setProducts(value: readonly string[], force = false) {
      if (!force && JSON.stringify(products) === JSON.stringify(value)) return
      generation += 1
      products = [...value]
      admitted = new Set(products.slice(0, 8))
      lastPublished = ''
      emit(true)
      // A still-visible row has no intersection change after a new authority.
      // Renew observation so the browser publishes its current visibility.
      for (const [target, product] of targets) {
        observer?.unobserve(target)
        if (products.includes(product)) observer?.observe(target)
      }
    },
    showMore() {
      for (const product of products.filter(product => !admitted.has(product)).slice(0, 8)) admitted.add(product)
      emit()
    },
    observe(symbol: string, target: Element | null) {
      for (const [element, product] of targets) if (product === symbol && element !== target) { observer?.unobserve(element); targets.delete(element) }
      if (target && !targets.has(target)) { targets.set(target, symbol); observer?.observe(target) }
    },
    dispose() { disposed = true; generation += 1; observer?.disconnect(); targets.clear() },
  }
}
