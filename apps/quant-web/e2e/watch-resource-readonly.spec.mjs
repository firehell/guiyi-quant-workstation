import { expect, test } from '@playwright/test'

test.skip(process.env.REAL_DEVELOP !== '1', 'Requires independent development API/Web')
test('serial repeated chart visits retain bounded caches and release request owners', async ({ page }) => {
  test.setTimeout(180000)
  const samples = [], errors = []
  page.on('pageerror', error => errors.push(error.message))
  for (let index = 0; index < 12; index++) {
    const symbol = index % 2 ? 'rb' : 'jm'
    const path = `/market/chart?view=newow&symbol=${symbol}&strategy=oscillation&series_kind=actual_dominant&frequency=1d`
    const proof = page.waitForResponse(response => {
      const url = new URL(response.url())
      return url.pathname.endsWith('/strategy-detail') && url.searchParams.get('section') === 'chart'
        && url.searchParams.get('product')?.toLowerCase() === symbol && response.status() === 200
    }, { timeout: 20000 })
    if (index === 0) await page.goto(path)
    else await page.evaluate(async path => { await document.querySelector('#app').__vue_app__.config.globalProperties.$router.push(path) }, path)
    await proof
    await expect(page.getByTestId('newow-product-chart-stage')).toBeVisible({ timeout: 20000 })
    const sample = await page.evaluate(async () => {
      const { newowSessionResources } = await import('/src/utils/newowSessionResources.ts')
      const { detailPriceCacheStats } = await import('/src/api/detailPriceCache.ts')
      return { session: newowSessionResources.stats(), prices: detailPriceCacheStats(), heap: performance.memory?.usedJSHeapSize ?? null }
    })
    expect(sample.session.bytes).toBeLessThanOrEqual(sample.session.maxBytes)
    expect(sample.session.entries).toBeLessThanOrEqual(sample.session.maxEntries)
    samples.push({ index, symbol, ...sample })
  }
  // Leaving the chart must unsubscribe its in-flight shared resources, without a background warmup.
  await page.evaluate(async () => { await document.querySelector('#app').__vue_app__.config.globalProperties.$router.push('/market/chart?view=free&symbol=jm&series_kind=actual_dominant&frequency=1d') })
  await expect.poll(() => page.evaluate(async () => {
    const { newowSessionResources } = await import('/src/utils/newowSessionResources.ts')
    return newowSessionResources.stats().pending
  })).toBe(0)
  console.log(JSON.stringify({ resourceVisitSamples: samples, errors }))
  expect(errors).toEqual([])
})

test('current reference readiness stays explicit while the real price chart remains usable', async ({ page }) => {
  const referenceRead = page.waitForResponse(response => {
    const url = new URL(response.url())
    return url.pathname.endsWith('/strategy-detail') && url.searchParams.get('section') === 'reference'
      && url.searchParams.get('reference_part') === 'panel'
  }, { timeout: 30000 })
  await page.goto('/market/chart?view=newow&symbol=jm&strategy=oscillation&series_kind=actual_dominant&frequency=1d')
  const chart = page.getByTestId('newow-product-chart-stage')
  await expect(chart).toBeVisible({ timeout: 20000 })
  const reference = page.getByRole('region', { name: 'Newow 参考与解释', exact: true })
  await reference.scrollIntoViewIfNeeded()
  const response = await referenceRead
  if (response.status() === 200) {
    await expect(reference.getByTestId('newow-reference-summary')).toBeVisible()
    console.log(JSON.stringify({ currentReferenceReadiness: 'verified' }))
  } else {
    expect(response.status()).toBe(503)
    expect((await response.json()).detail.code).toBe('SOURCE_IDENTITY_UNVERIFIED')
    await expect(reference.getByRole('alert')).toBeVisible()
    await expect(reference.getByTestId('newow-reference-summary')).toHaveCount(0)
    console.log(JSON.stringify({ currentReferenceReadiness: 'SOURCE_IDENTITY_UNVERIFIED', numericalAcceptance: 'pending' }))
  }
  await expect(chart).toBeVisible()
})
