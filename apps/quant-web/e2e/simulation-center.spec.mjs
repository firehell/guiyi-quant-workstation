import { expect, test } from '@playwright/test'

const now = '2026-11-27T21:03:00+08:00'

test('simulation center reports absent cabinet configuration', async ({ page }) => {
  await page.route('**/api/v1/simulations', route => route.fulfill({ json: {
    version: '0.1.0', source: 'SIMNOW_CTP', status: 'NOT_CONFIGURED', selected: null,
    accounts: [], readback: null, equity: [], fills: [], next_fill: null,
  } }))
  await page.goto('/simulations')
  await expect(page.getByRole('heading', { name: '模拟交易中心' })).toBeVisible()
  await expect(page.getByText('尚未配置 SimNow 账户读回。')).toBeVisible()
  await expect(page.getByRole('navigation', { name: '模拟交易中心导航' }).getByRole('link')).toHaveCount(5)
})

test('account selection only renders that account and native read status', async ({ page }) => {
  await page.route('**/api/v1/simulations**', route => {
    const alias = new URL(route.request().url()).searchParams.get('account') ?? 'trial-a'
    const accounts = [
      { alias: 'trial-a', deployment: { strategy_id: 'htdy_60m', formula_version: 'test-v1',
        profile_id: 'fixed-one-lot', risk_policy_version: 'risk-v1', instruments: ['SHFE:RB2701'] },
        status: 'OBSERVING', status_at: now },
      { alias: 'trial-b', deployment: null, status: 'DISCONNECTED', status_at: now },
    ]
    return route.fulfill({ json: {
      version: '0.1.0', source: 'SIMNOW_CTP', status: 'AVAILABLE', selected: alias, accounts,
      readback: alias === 'trial-a' ? { observed_at: now, trading_day: '2026-11-30',
        account: { equity: '100.01', available: '84', margin: '16.01', currency: 'CNY' },
        positions: [], orders: [] } : null,
      equity: alias === 'trial-a' ? [{ observed_at: now, equity: '100.01' }] : [],
      fills: [], next_fill: null,
    } })
  })
  await page.goto('/simulations')
  await expect(page.getByText('¥ 100.01', { exact: true })).toBeVisible()
  await page.getByRole('link', { name: '交易记录' }).click()
  await expect(page.getByText('最近完整读回为空仓。')).toBeVisible()
  await page.getByRole('link', { name: '策略运行' }).click()
  await expect(page.getByText('火天大有 60m', { exact: true })).toBeVisible()
  await page.getByRole('combobox', { name: '账户' }).selectOption('trial-b')
  await expect(page.getByText('连接中断', { exact: true })).toBeVisible()
  await expect(page.getByText('尚无完整柜台读回')).toBeVisible()
  await expect(page.getByText('火天大有 60m', { exact: true })).toHaveCount(0)
  await page.getByRole('link', { name: '绩效分析' }).click()
  await expect(page.getByText('暂无权益采样。')).toBeVisible()
})

test('registered account is selectable before its first native readback', async ({ page }) => {
  await page.route('**/api/v1/simulations**', route => route.fulfill({ json: {
    version: '0.1.1', source: 'SIMNOW_CTP', status: 'AVAILABLE', selected: 'registered-only',
    accounts: [{ alias: 'registered-only', deployment: null, status: 'REGISTERED', status_at: now }],
    readback: null, equity: [], fills: [], next_fill: null,
  } }))
  await page.goto('/simulations')
  await expect(page.getByRole('combobox', { name: '账户' })).toHaveValue('registered-only')
  await expect(page.getByText('已登记', { exact: true })).toBeVisible()
  await expect(page.getByText('尚无完整柜台读回')).toBeVisible()
  await expect(page.getByRole('region', { name: '账户摘要' }).locator('dd')).toHaveText(['—', '—', '—', '—'])
  await page.getByRole('link', { name: '交易记录' }).click()
  await expect(page.getByText('最近完整读回为空仓。')).toHaveCount(0)
})
