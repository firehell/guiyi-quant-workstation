import { expect, test } from '@playwright/test'

import { mockAlertMarkerSurface, mockWorkspace, research } from './market-research.helpers.mjs'

function rangeBars(start, count) {
  return Array.from({ length: count }, (_, index) => {
    const time = new Date(Date.UTC(2026, 0, 1, 0, start + index * 15)).toISOString()
    return {
      bar_end: time,
      trading_day: time.slice(0, 10),
      open: 100,
      high: 101,
      low: 99,
      close: 100,
      volume: 1_000,
      turnover: 10_000,
      open_interest: 2_000,
    }
  })
}

async function mockRangeWorkspace(page, { total = 540 } = {}) {
  const requests = []
  const all = rangeBars(0, total)
  await mockWorkspace(page, { json: research() }, {
    marketRequests: requests,
    barsPage(request) {
      if (!request.before) {
        const first = all.slice(Math.max(0, total - 300))
        return {
          bars: first,
          page: {
            has_more_before: total > first.length,
            next_before: total > first.length ? first[0].bar_end : null,
          },
        }
      }
      if (total > 600 && request.before === all[total - 300].bar_end) {
        const second = all.slice(total - 600, total - 300)
        return {
          bars: second,
          page: { has_more_before: true, next_before: second[0].bar_end },
        }
      }
      const first = all.slice(0, total > 600 ? total - 600 : total - 300)
      return { bars: first, page: { has_more_before: false, next_before: null } }
    },
  })
  await mockAlertMarkerSurface(page)
  return { requests, all }
}

async function openSettings(page) {
  await page.getByRole('button', { name: '图表设置', exact: true }).click()
}

async function enableRangeDetector(page) {
  await openSettings(page)
  const toggle = page.getByRole('switch', { name: '显示箱体识别', exact: true })
  if (!(await toggle.isChecked())) await toggle.click()
  await page.keyboard.press('Escape')
}

test.describe('Range Detector chart overlay', () => {
  test('is disabled by default', async ({ page }) => {
    await mockRangeWorkspace(page)
    await page.goto('/market/chart?symbol=ag&series_kind=actual_dominant&frequency=15m')

    await openSettings(page)
    await expect(page.getByRole('switch', { name: '显示箱体识别', exact: true })).toHaveCount(1)
    await expect(page.locator('.product-workspace__kline')).toHaveAttribute('data-range-detector-enabled', 'false')
  })

  test('enabling loads earlier pages through the fixed warm-up boundary', async ({ page }) => {
    const { requests } = await mockRangeWorkspace(page)
    await page.goto('/market/chart?symbol=ag&series_kind=actual_dominant&frequency=15m')
    await enableRangeDetector(page)

    const kline = page.locator('.product-workspace__kline')
    await expect.poll(() => requests.length).toBeGreaterThanOrEqual(2)
    await expect(page.getByTestId('product-status-strip')).toContainText('540 bars')
    await expect(kline).toHaveAttribute('data-range-detector-warmup', 'ready')
    await expect(kline).toHaveAttribute('data-range-detector-anchor', /T/)
  })

  test('freezes its anchor after warm-up', async ({ page }) => {
    const { requests } = await mockRangeWorkspace(page, { total: 720 })
    await page.goto('/market/chart?symbol=ag&series_kind=actual_dominant&frequency=15m')
    await enableRangeDetector(page)
    const kline = page.locator('.product-workspace__kline')
    await expect(kline).toHaveAttribute('data-range-detector-warmup', 'ready')
    const anchor = await kline.getAttribute('data-range-detector-anchor')
    const chartBox = await page.locator('.chart').boundingBox()
    for (let index = 0; index < 2; index += 1) {
      await page.mouse.move(chartBox.x + chartBox.width * 0.08, chartBox.y + chartBox.height * 0.5)
      await page.mouse.down()
      await page.mouse.move(chartBox.x + chartBox.width * 0.94, chartBox.y + chartBox.height * 0.5, { steps: 12 })
      await page.mouse.up()
    }
    await expect.poll(() => requests.length).toBeGreaterThanOrEqual(3)
    expect(await kline.getAttribute('data-range-detector-anchor')).toBe(anchor)
  })

  test('renders ranges only after anchor readiness', async ({ page }) => {
    await mockRangeWorkspace(page)
    await page.goto('/market/chart?symbol=ag&series_kind=actual_dominant&frequency=15m')
    const kline = page.locator('.product-workspace__kline')
    const shell = page.getByTestId('kline-shell')
    await expect(shell).toHaveAttribute('data-range-detector-range-count', '0')
    await enableRangeDetector(page)
    await expect(kline).toHaveAttribute('data-range-detector-warmup', 'ready')
    await expect(shell).toHaveAttribute('data-range-detector-range-count', /[1-9]/)
  })

  test('hover keeps the causal warning visible', async ({ page }) => {
    await mockRangeWorkspace(page)
    await page.goto('/market/chart?symbol=ag&series_kind=actual_dominant&frequency=15m')
    await enableRangeDetector(page)
    const box = await page.getByTestId('kline-shell').boundingBox()
    await page.mouse.move(box.x + box.width * 0.86, box.y + 220)
    await expect(page.getByText('箱体起点为回画展示；策略自确认时刻起才可使用')).toBeVisible()
  })

  test('persists the enabled switch through v8 localStorage', async ({ page }) => {
    await mockRangeWorkspace(page)
    await page.goto('/market/chart?symbol=ag&series_kind=actual_dominant&frequency=15m')
    await enableRangeDetector(page)
    await page.reload()
    await expect(page.locator('.product-workspace__kline')).toHaveAttribute('data-range-detector-enabled', 'true')
  })

  test('switching frequency replaces the deterministic Range source identity', async ({ page }) => {
    await mockRangeWorkspace(page)
    await page.goto('/market/chart?symbol=ag&series_kind=actual_dominant&frequency=15m')
    await enableRangeDetector(page)
    const kline = page.locator('.product-workspace__kline')
    const prior = await kline.getAttribute('data-range-detector-source-identity')
    await page.getByRole('group', { name: '周期' }).getByRole('button', { name: '5m', exact: true }).click()
    await expect(kline).toHaveAttribute('data-range-detector-source-identity', /:5m$/)
    expect(await kline.getAttribute('data-range-detector-source-identity')).not.toBe(prior)
  })

  test('keeps SuBing ribbon and HTDY paths available', async ({ page }) => {
    await mockRangeWorkspace(page)
    await page.goto('/market/chart?symbol=ag&series_kind=actual_dominant&frequency=15m')
    await page.getByRole('group', { name: 'Overlay' }).getByRole('button', { name: '苏冰', exact: true }).click()
    await expect(page.locator('.product-workspace__kline')).toHaveAttribute('data-subing-ema-ribbon', 'true')
    await page.getByRole('group', { name: 'Overlay' }).getByRole('button', { name: '火天大有', exact: true }).click()
    await expect(page.getByTestId('htdy-chart-legend')).toBeVisible()
  })

  test('retains the range layer at narrow width and fullscreen toggle', async ({ page }) => {
    await mockRangeWorkspace(page)
    await page.setViewportSize({ width: 820, height: 720 })
    await page.goto('/market/chart?symbol=ag&series_kind=actual_dominant&frequency=15m')
    await enableRangeDetector(page)
    await page.getByRole('button', { name: '全屏', exact: true }).click()
    await expect(page.locator('.product-workspace__kline')).toHaveAttribute('data-range-detector-warmup', 'ready')
  })

  test('marks insufficient history without drawing fabricated ranges', async ({ page }) => {
    await mockRangeWorkspace(page, { total: 420 })
    await page.goto('/market/chart?symbol=ag&series_kind=actual_dominant&frequency=15m')
    await enableRangeDetector(page)
    const kline = page.locator('.product-workspace__kline')
    await expect(kline).toHaveAttribute('data-range-detector-warmup', 'insufficient')
    await expect(page.getByTestId('kline-shell')).toHaveAttribute('data-range-detector-range-count', '0')
    await expect(page.getByText('箱体历史预载不足')).toBeVisible()
  })
})
