import request from './request'
import { homeSnapshotCache } from './homeSnapshotCache'
import { normalizeHomeCards, homeCardSessionKey, type HomePeriodFact, type HomeStrategy } from '../utils/newowHomeCards.ts'
import { newowSessionResources, newowResourceIdentity, invalidateNewowProduct, createReadQueue } from '../utils/newowSessionResources.ts'
import { NewowProductRequestError } from './newowProduct.ts'

let authority = ''
const homeRead = createReadQueue(2)
const performanceRead = createReadQueue(1)
export function configureHomeCardAuthority(value: string, force = false) {
  if (force) newowSessionResources.invalidate('home:')
  authority = value
}

export function peekNewowHomeCards(product: string) {
  const fresh = newowSessionResources.peek<ReturnType<typeof normalizeHomeCards>>(homeCardSessionKey([product], authority))
  if (fresh) return fresh
  const snapshot = homeSnapshotCache.peek<ReturnType<typeof normalizeHomeCards>>(`card:${product}`)
  if (!snapshot) return undefined
  try { return { ...normalizeHomeCards(snapshot.value, [product]), restored: true } } catch { void homeSnapshotCache.discard(`card:${product}`); return undefined }
}

export function getNewowHomeCards(products: string[], signal: AbortSignal) {
  const requestAuthority = authority
  return newowSessionResources.load(homeCardSessionKey(products, authority), async sharedSignal => {
    const value = await homeRead(() => {
      if (import.meta.env?.DEV) console.debug('Newow HTTP home-cards', products.join(','))
      return request.get<never, unknown>('/market/newow/home-cards', { params: { products: products.join(',') }, signal: sharedSignal, timeout: 180_000 })
    }, sharedSignal)
    const response = normalizeHomeCards(value, products)
    if (requestAuthority === authority && !sharedSignal.aborted) for (const card of response.items) {
      const display = structuredClone(card)
      for (const strategy of ['trend', 'oscillation'] as const) for (const period of ['1d', '1w'] as const) {
        delete display.strategies[strategy][period].snapshot_token
        delete display.strategies[strategy][period].page_performance
      }
      void homeSnapshotCache.put(`card:${card.product}`, { ...response, items: [display] })
    }
    return response
  }, newowResourceIdentity, signal).then(response => {
    if (signal.aborted) throw new DOMException('Aborted', 'AbortError')
    return response
  })
}

export function invalidateHomeCard(product: string) { newowSessionResources.invalidate(homeCardSessionKey([product], authority)) }

export async function getNewowHomePerformance(product: string, strategy: HomeStrategy, fact: HomePeriodFact, signal: AbortSignal): Promise<NonNullable<HomePeriodFact['page_performance']>> {
  if (!fact.as_of || !fact.snapshot_token) throw new Error('NEWOW_SNAPSHOT_REQUIRED')
  const owner = { product, strategy, as_of: fact.as_of, snapshot_token: fact.snapshot_token }
  const key = `newow:${product}:home-performance:${JSON.stringify([owner, fact.physical_contract, fact.formula_versions, fact.input_sha256, fact.data_revision_identity, 'newow_home_performance_v1'])}`
  return newowSessionResources.load(key, async sharedSignal => {
    const operation = performanceRead(() => {
      if (sharedSignal.aborted) throw new DOMException('Aborted', 'AbortError')
      if (import.meta.env?.DEV) console.debug('Newow HTTP home-card-performance', product, strategy)
      return request.get<never, { schema_version: string; product: string; strategy: string; snapshot_token: string; as_of: string; performance: NonNullable<HomePeriodFact['page_performance']> }>('/market/newow/home-card-performance', { params: owner, signal: sharedSignal, timeout: 180_000 })
    }, sharedSignal)
    let value
    try { value = await operation } catch (error) {
      const response = (error as { response?: { data?: { detail?: { code?: string } } } }).response
      if (response?.data?.detail?.code === 'NEWOW_SNAPSHOT_GENERATION_CONFLICT') {
        invalidateNewowProduct(product)
        throw new NewowProductRequestError('NEWOW_SNAPSHOT_GENERATION_CONFLICT', 'conflict')
      }
      throw error
    }
    if (value.schema_version !== 'newow_home_performance_v1' || value.product !== product || value.strategy !== strategy || value.snapshot_token !== fact.snapshot_token || value.as_of !== fact.as_of || !value.performance || !['ready', 'warming', 'unavailable'].includes(value.performance.status)) throw new Error('INVALID_HOME_PERFORMANCE')
    // Reuse the same strict field validator as the full card reader.
    const period = { ...fact, page_performance: value.performance }
    normalizeHomeCards({ schema_version: 'newow_home_cards_v2', requested_at: fact.display_as_of ?? fact.as_of, items: [{ product, strategies: { trend: { '1d': strategy === 'trend' ? period : { status: 'unavailable', state: null }, '1w': { status: 'unavailable', state: null } }, oscillation: { '1d': strategy === 'oscillation' ? period : { status: 'unavailable', state: null }, '1w': { status: 'unavailable', state: null } } } }] }, [product])
    return value.performance
  }, newowResourceIdentity, signal)
}


/** Fast historical display only. Current cards still use the verified reader. */
export async function getHomeDisplayCache(signal: AbortSignal) {
  const value = await request.get<never, { schema_version: string; stale: boolean; executable: boolean; items: Array<{ product: string; saved_at: string; card: unknown }> }>('/market/newow/home-card-display-cache', { signal, timeout: 3000 })
  if (value.schema_version !== 'newow_home_display_cache_v1' || value.stale !== true || value.executable !== false || !Array.isArray(value.items) || value.items.length > 60) throw new Error('INVALID_HOME_DISPLAY_CACHE')
  return value.items.map(item => {
    const savedAt = Date.parse(item.saved_at)
    if (!Number.isFinite(savedAt) || savedAt > Date.now() || Date.now() - savedAt > 7 * 86400_000) throw new Error('INVALID_HOME_DISPLAY_CACHE')
    const response = normalizeHomeCards({ schema_version: 'newow_home_cards_v2', requested_at: item.saved_at, items: [item.card] }, [item.product])
    return { product: item.product, response: { ...response, restored: true } }
  })
}
