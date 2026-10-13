import assert from 'node:assert/strict'
import test from 'node:test'
import { createHomeCardViewport } from '../src/utils/newowHomeViewport.ts'
import { createHomeCardLoader } from '../src/utils/newowHomeCards.ts'

const response = (product: string) => ({ schema_version: 'newow_home_cards_v2' as const, requested_at: '2026-10-13T03:00:00Z', items: [{ product, strategies: { trend: { '1d': { status: 'unavailable' as const, state: null }, '1w': { status: 'unavailable' as const, state: null } }, oscillation: { '1d': { status: 'unavailable' as const, state: null }, '1w': { status: 'unavailable' as const, state: null } } } }] })

test('viewport admission preserves page order, batches callbacks and requires explicit fallback expansion', async () => {
  const publishes: Array<{ products: readonly string[]; reset: boolean }> = []
  let callback!: IntersectionObserverCallback
  let disconnected = false
  const viewport = createHomeCardViewport((products, reset) => publishes.push({ products, reset }), cb => { callback = cb; return { observe() {}, unobserve() {}, disconnect() { disconnected = true } } })
  const products = Array.from({ length: 12 }, (_, i) => `p${11 - i}`)
  viewport.setProducts(products)
  assert.deepEqual(publishes[0], { products: products.slice(0, 8), reset: true })
  const target = {} as Element
  viewport.observe(products[10]!, target)
  callback([{ target, isIntersecting: true }] as IntersectionObserverEntry[], {} as IntersectionObserver)
  callback([{ target, isIntersecting: true }] as IntersectionObserverEntry[], {} as IntersectionObserver)
  await Promise.resolve()
  assert.equal(publishes.length, 2)
  assert.deepEqual(publishes[1], { products: [...products.slice(0, 8), products[10]!], reset: false })
  viewport.setProducts(['rb'])
  callback([{ target, isIntersecting: true }] as IntersectionObserverEntry[], {} as IntersectionObserver)
  await Promise.resolve()
  assert.deepEqual(publishes.at(-1), { products: ['rb'], reset: true })
  viewport.dispose(); assert.equal(disconnected, true)
  const fallback = createHomeCardViewport((products, reset) => publishes.push({ products, reset }), null)
  fallback.setProducts(products)
  assert.equal(publishes.at(-1)!.products.length, 8)
  fallback.showMore()
  assert.equal(publishes.at(-1)!.products.length, 12)
  assert.equal(publishes.at(-1)!.reset, false)
  fallback.dispose()
})

test('scroll admission does not cancel active requests or duplicate admitted products', async () => {
  const calls: Array<{ product: string; signal: AbortSignal; resolve: (value: ReturnType<typeof response>) => void }> = []
  const loader = createHomeCardLoader((products, signal) => new Promise(resolve => calls.push({ product: products[0]!, signal, resolve })), () => {})
  const first = loader.load(['rb', 'cu'])
  loader.admit(['rb', 'cu', 'a'])
  loader.admit(['a'])
  assert.equal(calls.length, 2)
  assert.ok(calls.every(call => !call.signal.aborted))
  calls[0]!.resolve(response('rb')); await new Promise(resolve => setImmediate(resolve))
  assert.deepEqual(calls.map(call => call.product), ['rb', 'cu', 'a'])
  calls[1]!.resolve(response('cu')); calls[2]!.resolve(response('a'))
  await first
  assert.ok(calls.every(call => !call.signal.aborted))
  loader.dispose()
})

test('authority refresh reobserves a row that remains visible beyond the initial eight', async () => {
  const publishes: readonly string[][] = []
  const values = publishes as string[][]
  let callback!: IntersectionObserverCallback
  let observes = 0
  const target = {} as Element
  const viewport = createHomeCardViewport(products => values.push([...products]), cb => {
    callback = cb
    return { observe(element) { observes += 1; callback([{ target: element, isIntersecting: true }] as IntersectionObserverEntry[], {} as IntersectionObserver) }, unobserve() {}, disconnect() {} }
  })
  const products = Array.from({ length: 12 }, (_, i) => `p${i}`)
  viewport.setProducts(products)
  viewport.observe('p10', target)
  await Promise.resolve()
  assert.ok(publishes.at(-1)!.includes('p10'))
  viewport.setProducts(products, true)
  await Promise.resolve()
  assert.equal(observes, 2)
  assert.ok(publishes.at(-1)!.includes('p10'))
  viewport.dispose()
})

test('newly visible rows receive the next slot before obsolete offscreen queue entries', async () => {
  const calls: Array<{ product: string; signal: AbortSignal; resolve: (value: ReturnType<typeof response>) => void }> = []
  const loader = createHomeCardLoader((products, signal) => new Promise(resolve => calls.push({ product: products[0]!, signal, resolve })), () => {})
  const pending = loader.load(['rb', 'cu', 'a', 'b'])
  loader.admit(['ag'])
  calls[0]!.resolve(response('rb')); await new Promise(resolve => setImmediate(resolve))
  assert.deepEqual(calls.map(call => call.product), ['rb', 'cu', 'ag'])
  assert.ok(calls.every(call => !call.signal.aborted))
  loader.dispose(); calls[1]!.resolve(response('cu')); calls[2]!.resolve(response('ag')); await pending
})
