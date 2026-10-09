export type HomeStrategy = 'trend' | 'oscillation'
export type HomePeriod = '1d' | '1w'
export type HomeState = 'BUILD' | 'HOLD' | 'CLEAR' | 'FLAT'
export interface HomePeriodFact {
  status: 'ready' | 'warming' | 'unavailable'
  state: HomeState | null
  reason_code?: string | null
  as_of?: string
  bar_end?: string
  physical_contract?: string
  segment_id?: string
  calculation_segment_id?: string
  source_identity?: string
  input_sha256?: string
  snapshot_token?: string
  formula_versions?: string[]
  freshness?: string
  reference_current?: string | null
  reference_cost?: string | null
  entry_signal_id?: string | null
  target?: string | null
  absorb?: string | null
  target_space_percent?: string | null
  recent_action?: { kind: 'BUILD' | 'CLEAR'; bar_end: string; signal_id: string } | null
  page_parity?: boolean
  executable?: boolean
}
export interface HomeCard { product: string; strategies: Record<HomeStrategy, Record<HomePeriod, HomePeriodFact>> }
export interface HomeCardsResponse { schema_version: 'newow_home_cards_v1'; requested_at: string; items: HomeCard[] }
export interface CardDelivery { card: HomeCard | null; loading: boolean; stale: boolean; failed: boolean }

export function normalizeHomeCards(value: unknown, products: readonly string[]): HomeCardsResponse {
  const response = value as HomeCardsResponse
  if (response?.schema_version !== 'newow_home_cards_v1' || !Array.isArray(response.items) || response.items.length !== products.length || !Number.isFinite(Date.parse(response.requested_at))) throw new Error('INVALID_HOME_CARDS')
  const seen = new Set<string>()
  for (const item of response.items) {
    if (!products.includes(item.product) || seen.has(item.product)) throw new Error('INVALID_HOME_CARDS')
    seen.add(item.product)
    for (const strategy of ['trend', 'oscillation'] as const) for (const period of ['1d', '1w'] as const) {
      const fact = item.strategies?.[strategy]?.[period]
      if (!fact || !['ready', 'warming', 'unavailable'].includes(fact.status)) throw new Error('INVALID_HOME_CARDS')
      if (fact.status === 'ready' && (!['BUILD', 'HOLD', 'CLEAR', 'FLAT'].includes(fact.state ?? '') || !fact.physical_contract || !fact.segment_id || !fact.calculation_segment_id || !fact.input_sha256 || !fact.formula_versions?.length || !Number.isFinite(Date.parse(fact.as_of ?? '')) || !Number.isFinite(Date.parse(fact.bar_end ?? '')) || fact.page_parity !== true || fact.executable !== false)) throw new Error('INVALID_HOME_CARDS')
      for (const key of ['target', 'absorb', 'reference_cost', 'reference_current', 'target_space_percent'] as const) if (fact[key] != null && (typeof fact[key] !== 'string' || !Number.isFinite(Number(fact[key])))) throw new Error('INVALID_HOME_CARDS')
      if (fact.status !== 'ready' && fact.state !== null) throw new Error('INVALID_HOME_CARDS')
    }
  }
  return response
}

/** Two workers; late/cancelled generations cannot replace a newer snapshot. */
export function createHomeCardLoader(fetch: (products: string[], signal: AbortSignal) => Promise<HomeCardsResponse>, publish: (items: Record<string, CardDelivery>) => void) {
  let generation = 0
  let controller: AbortController | null = null
  let items: Record<string, CardDelivery> = {}
  return {
    async load(products: readonly string[]) {
      const current = ++generation
      controller?.abort()
      controller = new AbortController()
      const signal = controller.signal
      items = Object.fromEntries(products.map(product => [product, { card: items[product]?.card ?? null, loading: true, stale: Boolean(items[product]?.card), failed: false }]))
      publish({ ...items })
      const batches: string[][] = []
      // Cold canonical reads can take tens of seconds per product. Publish each
      // product as soon as it finishes instead of hiding twelve behind one read.
      for (const product of products) batches.push([product])
      async function worker() {
        while (batches.length && current === generation) {
          const batch = batches.shift()!
          try {
            const response = normalizeHomeCards(await fetch(batch, signal), batch)
            if (current !== generation) return
            for (const card of response.items) items[card.product] = { card, loading: false, stale: false, failed: false }
          } catch {
            if (current !== generation) return
            for (const product of batch) items[product] = { card: items[product]?.card ?? null, loading: false, stale: Boolean(items[product]?.card), failed: true }
          }
          publish({ ...items })
        }
      }
      await Promise.all([worker(), worker()])
    },
    dispose() { ++generation; controller?.abort() },
  }
}
