import { expect, test } from '@playwright/test'

test.skip(process.env.REAL_BACKEND !== '1', 'explicit local candidate read-only acceptance only')
test.describe.configure({ timeout: 300_000 })

const cutoff = '2026-09-14T11:00:00+00:00'
const strategies = ['trend', 'oscillation', 'main_rise']

test('real candidate home keeps 60 products across cold, hard reload and SPA tab return', async ({ page }, testInfo) => {
  const errors = []
  page.on('pageerror', (error) => errors.push(error.message))
  const started = Date.now()
  await page.goto('/market')
  await expect(page.getByTestId('candidate-preview-banner')).toContainText('本地候选只读预览')
  await expect(page.locator('.market-home-list-heading')).toContainText('60', { timeout: 30_000 })
  await expect(page.locator('.table-wrap tbody tr')).toHaveCount(60, { timeout: 30_000 })
  const coldMs = Date.now() - started

  const reloadStarted = Date.now()
  await page.reload()
  await expect(page.locator('.table-wrap tbody tr')).toHaveCount(60, { timeout: 30_000 })
  const reloadMs = Date.now() - reloadStarted

  await page.getByRole('tab', { name: '消息' }).click()
  await expect(page.getByRole('tab', { name: '消息' })).toHaveAttribute('aria-selected', 'true')
  await page.getByRole('tab', { name: '市场' }).click()
  await expect(page.locator('.table-wrap tbody tr')).toHaveCount(60)
  await page.screenshot({ path: testInfo.outputPath('real-home-60.png'), fullPage: true })
  console.log(JSON.stringify({ evidence: 'real-home', coldMs, reloadMs, rows: 60, errors }))
  expect(errors).toEqual([])
})

test('real candidate covers AU/JM Newow weekly, AU seven-frequency Free and weekly complete-window action', async ({ page }, testInfo) => {
  const matrix = []
  for (const product of ['au', 'jm']) {
    for (const strategy of strategies) {
      await page.goto(`/market/chart?symbol=${product}&view=newow&strategy=${strategy}&series_kind=actual_dominant&frequency=1w`)
      const workspace = page.locator('[data-detail-workspace="newow"]')
      await expect(workspace).toBeVisible()
      await expect(page.getByTestId('newow-product-chart-stage')).toBeVisible()
      await expect.poll(async () => workspace.getAttribute('data-chart-state'), { timeout: 60_000 })
        .toMatch(/^(ready|warming|evidence_required|unavailable|stale|input_conflict)$/)
      matrix.push({ product, strategy, chart: await workspace.getAttribute('data-chart-state') })
    }
  }

  await page.goto('/market/chart?symbol=au&view=newow&strategy=trend&series_kind=actual_dominant&frequency=1w')
  await expect(page.getByTestId('newow-reference-summary')).toBeVisible({ timeout: 60_000 })
  await page.getByLabel('统计终点').fill('2026-09-14')
  await page.getByRole('button', { name: '应用统计窗口' }).click()
  await expect(page.getByRole('button', { name: '使用最近完整统计区间' })).toBeVisible({ timeout: 60_000 })
  await page.getByRole('button', { name: '使用最近完整统计区间' }).click()
  await expect(page.getByLabel('统计终点')).toHaveValue('2026-09-11')

  for (const frequency of ['1m', '5m', '15m', '30m', '60m', '1d', '1w']) {
    await page.goto(`/market/chart?symbol=au&view=free&series_kind=actual_dominant&frequency=${frequency}`)
    await expect(page.locator('[data-detail-ready="true"]')).toBeVisible({ timeout: 60_000 })
    matrix.push({ product: 'au', view: 'free', frequency })
  }
  await page.screenshot({ path: testInfo.outputPath('real-au-free-1w.png'), fullPage: true })
  console.log(JSON.stringify({ evidence: 'real-product-matrix', cutoff, matrix }))
})

test('real candidate keeps JM SuBing data gap explicit and Newow callouts inside the chart', async ({ page }, testInfo) => {
  const responsePromise = page.waitForResponse((response) => new URL(response.url()).pathname.endsWith('/market/jm/subing/reference'))
  await page.goto('/market/chart?symbol=jm&view=subing')
  await expect(page.locator('[data-detail-workspace="subing"]')).toBeVisible()
  const response = await responsePromise
  expect(response.status()).toBe(409)
  const body = await response.json()
  expect(body.detail.code).toBe('SUBING_REFERENCE_DATA_UNAVAILABLE')
  expect(body.detail.diagnostic.stage).toBe('physical_contract_replay')
  expect(body.detail.diagnostic.reason).toBe('DATASET_OR_PARTITION_MISSING')
  await expect(page.getByText(/物理合约回放失败：行情数据集或分区缺失/)).toBeVisible()

  await page.goto('/market/chart?symbol=au&view=newow&strategy=trend&series_kind=actual_dominant&frequency=1w')
  const stage = page.getByTestId('newow-product-chart-stage')
  await expect(stage).toBeVisible()
  await expect(page.locator('[data-detail-workspace="newow"]')).toHaveAttribute('data-chart-state', 'ready', { timeout: 60_000 })
  await expect.poll(async () => stage.getAttribute('data-action-ids'), { timeout: 60_000 }).toMatch(/\S/)
  const callouts = stage.locator('.newow-product-chart-stage__action-label')
  const count = await callouts.count()
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: width === 390 ? 844 : 900 })
    await stage.scrollIntoViewIfNeeded()
    const chartBox = await stage.locator('.newow-product-chart-stage__chart').boundingBox()
    expect(chartBox).not.toBeNull()
    for (const box of await callouts.evaluateAll((nodes) => nodes.map((node) => {
      const rect = node.getBoundingClientRect()
      return { left: rect.left, right: rect.right, top: rect.top, bottom: rect.bottom }
    }))) {
      expect(box.left).toBeGreaterThanOrEqual(chartBox.x - 1)
      expect(box.right).toBeLessThanOrEqual(chartBox.x + chartBox.width + 1)
      expect(box.top).toBeGreaterThanOrEqual(chartBox.y - 1)
      expect(box.bottom).toBeLessThanOrEqual(chartBox.y + chartBox.height + 1)
    }
  }
  await stage.getByRole('button', { name: '图表全屏' }).click()
  await expect(stage.getByRole('button', { name: '退出图表全屏' })).toBeVisible()
  await stage.getByRole('button', { name: '退出图表全屏' }).click()
  await expect(stage.getByRole('button', { name: '图表全屏' })).toBeVisible()
  await page.screenshot({ path: testInfo.outputPath('real-au-newow-390.png'), fullPage: true })
  console.log(JSON.stringify({ evidence: 'real-jm-gate-and-callouts', jmStatus: response.status(), diagnostic: body.detail.diagnostic, calloutCount: count }))
})
