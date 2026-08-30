import { expect, test } from '@playwright/test'
import {
  bar,
  research,
  subing,
  mockProductIdentityWorkspace,
  selectProduct,
  releaseIdentityFacts,
  enableSubingStrategyPerformance,
} from './market-research.helpers.mjs'

test.describe('Alert Scope', () => {
test('Product Workspace identity invalidates AG facts before delayed JM Market acceptance', async ({ page }) => {
  const { calls, gates } = await mockProductIdentityWorkspace(page)
  releaseIdentityFacts(gates, 'initialAg')
  await page.goto('/market/chart?symbol=ag&series_kind=actual_dominant&frequency=5m')

  await expect(page.getByTestId('product-check-sidebar')).toContainText('AG OLD Scope')
  await expect(page.getByTestId('product-check-background')).toContainText('6.1%')
  await selectProduct(page, 'JM 焦煤')
  await expect.poll(() => calls.bars.filter((item) => item === 'jm').length).toBe(1)

  expect(calls.research.filter((item) => item === 'jm')).toEqual([])
  expect(calls.subing.filter((item) => item === 'jm')).toEqual([])
  expect(calls.scope.filter((item) => item === 'jm')).toEqual([])
  expect(calls.events.filter((item) => item === 'jm')).toEqual([])
  await expect(page.getByTestId('product-check-sidebar')).toContainText('JM 焦煤')
  await expect(page.getByTestId('product-check-background')).toContainText('正在读取周线 / 日线…')
  await expect(page.getByTestId('product-check-background')).not.toContainText('6.1%')
  await expect(page.getByTestId('subing-current-research')).toContainText('苏冰观察加载中')
  await expect(page.getByTestId('subing-alert-scope')).not.toContainText('AG OLD Scope')
  await expect(page.getByTestId('subing-alert-scope').getByRole('switch')).toHaveClass(/n-switch--disabled/)
  await expect(page.getByTestId('subing-alert-scope').getByRole('switch')).toHaveClass(/n-switch--loading/)
  expect(calls.put).toEqual([])

  gates.jmBars.resolve()
  await expect.poll(() => calls.research.filter((item) => item === 'jm').length).toBe(1)
  await expect.poll(() => calls.subing.filter((item) => item === 'jm').length).toBe(1)
  await expect.poll(() => calls.scope.filter((item) => item === 'jm').length).toBe(1)
  await expect.poll(() => calls.events.filter((item) => item === 'jm').length).toBe(1)
  await expect(page.getByTestId('subing-alert-scope').getByRole('switch')).toHaveClass(/n-switch--disabled/)
  await expect(page.getByTestId('subing-alert-scope').getByRole('switch')).toHaveClass(/n-switch--loading/)

  gates.jmResearch.resolve()
  gates.jmSubing.resolve()
  gates.jmScope.resolve()
  gates.jmEvents.resolve()
  await expect(page.getByTestId('product-check-background')).toContainText('-4.2%')
  await expect(page.locator('.subing-panel__factor').filter({ hasText: 'Primary Factor' })).toContainText('S5 -4.2 bps/bar')
  await expect(page.getByTestId('subing-alert-scope')).toContainText('JM JM Scope')
  await expect(page.getByTestId('subing-alert-scope').getByRole('switch')).not.toHaveClass(/n-switch--disabled/)
  await expect(page.getByTestId('subing-strategy-event')).toContainText('建多')
  expect(calls.put).toEqual([])
})

test('Product Workspace aborts the old full-history performance request on symbol change', async ({ page }) => {
  const failedPerformanceRequests = []
  page.on('requestfailed', (request) => {
    if (request.url().includes('/research/subing-strategy/performance')) {
      failedPerformanceRequests.push(request.url())
    }
  })
  const { calls, gates } = await mockProductIdentityWorkspace(page)
  for (const kind of ['Research', 'Subing', 'Scope', 'Events']) {
    gates[`initialAg${kind}`].resolve()
  }
  await page.goto('/market/chart?symbol=ag&series_kind=actual_dominant&frequency=5m')
  await expect.poll(() => calls.performance).toEqual(['ag'])

  await selectProduct(page, 'JM 焦煤')
  gates.jmBars.resolve()
  for (const kind of ['Research', 'Subing', 'Performance', 'Scope', 'Events']) {
    gates[`jm${kind}`].resolve()
  }

  await expect.poll(() => calls.performance).toEqual(['ag', 'jm'])
  await expect(page.getByTestId('subing-strategy-performance')).toHaveCount(0)
  await enableSubingStrategyPerformance(page)
  await expect(page.getByTestId('subing-strategy-performance')).toContainText('JM')
  await expect.poll(() => failedPerformanceRequests.some((url) => url.includes('symbol=ag'))).toBe(true)
})

test('Product Workspace identity replays a frequency change made during delayed symbol Market acceptance', async ({ page }) => {
  const { calls, gates } = await mockProductIdentityWorkspace(page)
  releaseIdentityFacts(gates, 'initialAg')
  await page.goto('/market/chart?symbol=ag&series_kind=actual_dominant&frequency=5m')
  await expect(page.getByTestId('product-check-background')).toContainText('6.1%')

  await selectProduct(page, 'JM 焦煤')
  await expect.poll(() => calls.bars.filter((item) => item === 'jm').length).toBe(1)
  await page.getByRole('group', { name: '周期' }).getByRole('button', { name: '15m', exact: true }).click()

  await expect.poll(() => calls.bars.filter((item) => item === 'jm').length).toBe(2)
  expect(calls.research.filter((item) => item === 'jm')).toEqual([])
  expect(calls.scope.filter((item) => item === 'jm')).toEqual([])
  await expect(page.getByTestId('product-check-background')).not.toContainText('6.1%')
  await expect(page.getByTestId('subing-alert-scope').getByRole('switch')).toHaveClass(/n-switch--disabled/)

  gates.jm15mBars.resolve()
  await expect.poll(() => calls.research.filter((item) => item === 'jm').length).toBe(1)
  await expect.poll(() => calls.scope.filter((item) => item === 'jm').length).toBe(1)
  gates.jmResearch.resolve()
  gates.jmSubing.resolve()
  gates.jmScope.resolve()
  gates.jmEvents.resolve()
  await expect(page.getByTestId('product-check-background')).toContainText('-4.2%')
  await expect(page.getByTestId('subing-alert-scope')).toContainText('JM JM Scope')

  gates.jmBars.resolve()
  await page.waitForTimeout(100)
  await expect(page.getByRole('group', { name: '周期' }).getByRole('button', { name: '15m', exact: true })).toHaveClass(/n-button--primary-type/)
  expect(calls.research.filter((item) => item === 'jm')).toHaveLength(1)
  expect(calls.scope.filter((item) => item === 'jm')).toHaveLength(1)
  expect(calls.put).toEqual([])
})

test('Product Workspace identity keeps only the final AG generation across AG to JM to AG', async ({ page }) => {
  const { calls, gates } = await mockProductIdentityWorkspace(page)
  await page.goto('/market/chart?symbol=ag&series_kind=actual_dominant&frequency=5m')
  await expect.poll(() => calls.research.filter((item) => item === 'ag').length).toBe(1)
  await expect.poll(() => calls.scope.filter((item) => item === 'ag').length).toBe(1)

  await selectProduct(page, 'JM 焦煤')
  await expect.poll(() => calls.bars.filter((item) => item === 'jm').length).toBe(1)
  await selectProduct(page, 'AG 白银')
  await expect.poll(() => calls.research.filter((item) => item === 'ag').length).toBe(2)
  await expect.poll(() => calls.subing.filter((item) => item === 'ag').length).toBe(2)
  await expect.poll(() => calls.scope.filter((item) => item === 'ag').length).toBe(2)
  await expect.poll(() => calls.events.filter((item) => item === 'ag').length).toBe(2)

  releaseIdentityFacts(gates, 'finalAg')
  await expect(page.getByTestId('product-check-sidebar')).toContainText('AG 白银')
  await expect(page.getByTestId('product-check-background')).toContainText('9.2%')
  await expect(page.locator('.subing-panel__factor').filter({ hasText: 'Primary Factor' })).toContainText('S5 9.2 bps/bar')
  await expect(page.getByTestId('subing-alert-scope')).toContainText('AG FINAL Scope')

  releaseIdentityFacts(gates, 'initialAg')
  gates.jmBars.resolve()
  await expect.poll(() => calls.bars.filter((item) => item === 'jm').length).toBe(1)
  await page.waitForTimeout(100)
  expect(calls.research.filter((item) => item === 'jm')).toEqual([])
  expect(calls.scope.filter((item) => item === 'jm')).toEqual([])
  await expect(page.getByTestId('product-check-background')).toContainText('9.2%')
  await expect(page.getByTestId('subing-alert-scope')).toContainText('AG FINAL Scope')
  await expect(page.getByTestId('subing-alert-scope')).not.toContainText('AG OLD Scope')
  expect(calls.put).toEqual([])
})
})
