import { expect, test } from '@playwright/test'

test.skip(process.env.REAL_DEVELOP !== '1', 'Requires this task independent development preview')

test('real selected reference parts preserve complete metrics and keep page bodies separate', async ({ page, request }) => {
  test.setTimeout(90000)
  const chart = await request.get('/api/v1/market/newow/strategy-detail', { params: {
    product: 'jm', strategy: 'oscillation', frequency: '1d', section: 'chart', resolve_current: true,
  } })
  expect(chart.status()).toBe(200)
  const accepted = await chart.json()
  const common = { product: 'jm', strategy: 'oscillation', frequency: '1d', section: 'reference',
    as_of: accepted.meta.as_of, snapshot_token: accepted.meta.snapshot_token }
  const legacyResponse = await request.get('/api/v1/market/newow/strategy-detail', { params: common })
  expect(legacyResponse.status()).toBe(200)
  const legacyText = await legacyResponse.text(), legacy = JSON.parse(legacyText).reference.value
  const results = {}, sizes = { legacy: Buffer.byteLength(legacyText) }
  for (const part of ['overview', 'curve', 'history']) {
    const started = Date.now()
    const response = await request.get('/api/v1/market/newow/strategy-detail', { params: {
      ...common, reference_part: part, reference_mode: 'page_ordinary',
      performance_since: legacy.performance_since, performance_through: legacy.performance_through,
    } })
    expect(response.status()).toBe(200)
    const raw = await response.text(), body = JSON.parse(raw)
    results[part] = body.reference.value
    sizes[part] = { decodedBytes: Buffer.byteLength(raw), elapsedMs: Date.now() - started }
    expect(body.meta.snapshot_token).toBe(accepted.meta.snapshot_token)
    expect(body.reference.value.reference_input_sha256).toBe(legacy.reference_input_sha256)
  }
  expect(results.overview.recent_items.length).toBeLessThanOrEqual(3)
  expect(results.curve.curve.metrics.return_percentage_points).toBe(legacy.page_performance.ordinary.summary.cumReturn)
  expect(String(results.curve.curve.metrics.win_rate_pct)).toBe(String(legacy.page_performance.ordinary.summary.accuracy))
  expect(results.curve.curve.metrics.drawdown).toBe(legacy.page_performance.ordinary.summary.maxDrawdown)
  expect(results.curve.curve.total_points).toBe(legacy.page_performance.ordinary.dates.length)
  expect(results.curve.curve.points.length).toBeLessThanOrEqual(2000)
  expect(results.history.items.length).toBeLessThanOrEqual(50)
  expect(results.history).not.toHaveProperty('curve')
  expect(results.history).not.toHaveProperty('summary')
  expect(results.overview).not.toHaveProperty('curve')
  console.log(JSON.stringify({ realReferenceSizes: sizes }))

  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  await page.goto('/market/chart?view=newow&symbol=jm&strategy=oscillation&series_kind=actual_dominant&frequency=1d')
  await expect(page.getByTestId('newow-product-chart-stage')).toBeVisible({ timeout: 20000 })
  const reference = page.getByRole('region', { name: 'Newow 参考与解释', exact: true })
  await reference.scrollIntoViewIfNeeded()
  await expect(reference.getByTestId('newow-reference-summary')).toBeVisible({ timeout: 20000 })
  await expect(reference.getByRole('alert')).toHaveCount(0)
  await page.screenshot({ path: '/private/tmp/guiyi-multi-product-real-desktop.png' })
  await page.setViewportSize({ width: 390, height: 844 })
  await expect(reference.getByTestId('newow-reference-summary')).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  await page.screenshot({ path: '/private/tmp/guiyi-multi-product-real-mobile.png' })
  expect(errors).toEqual([])
})
