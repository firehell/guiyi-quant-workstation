import { newowReferencePrice } from './newowPagePresentation.ts'

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

export const homeStateLabels = { BUILD: '建仓', HOLD: '持有', CLEAR: '清仓', FLAT: '空仓' } as const
export const homeStateIcons = { BUILD: '▲', HOLD: '✓', CLEAR: '↘', FLAT: '○' } as const

/** Presentation of the explicit daily state, never a new strategy calculation. */
export function homeReferenceDisplay(fact?: HomePeriodFact) {
  const target = fact?.status === 'ready' && (fact.state === 'BUILD' || fact.state === 'HOLD')
  const absorb = fact?.status === 'ready' && (fact.state === 'CLEAR' || fact.state === 'FLAT')
  return { label: target ? '目标' : absorb ? '吸筹' : '目标/吸筹', text: newowReferencePrice(target ? fact?.target : absorb ? fact?.absorb : null).replace(/^—$/, '--') }
}

export function homePeriodDisplay(fact?: HomePeriodFact) {
  if (fact?.status === 'ready' && fact.state) return { label: homeStateLabels[fact.state], icon: homeStateIcons[fact.state], tone: fact.state.toLowerCase() }
  return { label: fact?.status === 'warming' ? '预热中' : fact ? '不可用' : '加载中', icon: '—', tone: 'pending' }
}

/** Day/week state alignment only. It does not infer a trend from price or scores. */
export function homeDirectionDisplay(day?: HomePeriodFact, week?: HomePeriodFact) {
  const identified = (fact?: HomePeriodFact): fact is HomePeriodFact & { state: HomeState } => Boolean(fact?.status === 'ready' && fact.state && fact.physical_contract && fact.segment_id && fact.calculation_segment_id && fact.input_sha256 && fact.formula_versions?.length)
  if (!identified(day) || !identified(week)) return { label: '待确认', tone: 'pending' }
  const up = (state: HomeState) => state === 'BUILD' || state === 'HOLD'
  if (up(day.state) !== up(week.state)) return { label: '日周分歧', tone: 'mixed' }
  return up(day.state) ? { label: '日周向上', tone: 'up' } : { label: '日周向下', tone: 'down' }
}

export function homeDeliveryNotice(delivery?: CardDelivery) {
  if (delivery?.stale) return delivery.loading ? '策略刷新中，保留上次快照' : '策略刷新失败，保留上次快照'
  if (delivery?.failed) return '策略读取失败，可刷新重试'
  return delivery?.loading || !delivery ? '策略读取中' : null
}

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
