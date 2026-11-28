import { test, expect } from '@playwright/test'

test('opens the six-strategy directory and preserves domain evidence during partial failure', async ({ page }) => {
  const definitions = [
    ['newow_trend', 'newow', '趋势', 'BASE', []],
    ['newow_oscillation', 'newow', '震荡', 'BASE', []],
    ['newow_main_rise', 'newow', '主升浪', 'BASE', []],
    ['newow_dual_fusion', 'newow', '双策略融合', 'COMPOSITE', ['newow_trend', 'newow_oscillation']],
    ['htdy_60m', 'htdy', '火天大有 60m', 'DOMAIN_STRATEGY', []],
    ['subing_portfolio_16', 'subing', '苏冰共享 Paper 组合', 'PORTFOLIO', []],
  ].map(([strategy_id, domain, name, kind, dependencies]) => ({
    strategy_id, domain, name, kind, dependencies, description: name, lifecycle: 'ACTIVE',
  }))
  const seen = []
  let firstBusy = true
  await page.route('**/api/v1/strategies**', async route => {
    const url = new URL(route.request().url())
    const [, id, resource] = url.pathname.split('/strategies')[1].split('/')
    seen.push(route.request().method())
    const stamp = '2026-11-27T07:00:00+00:00'
    const status = (state, source, data = {}) => ({ status: state, source, source_as_of: stamp, ...data })
    if (!id) return route.fulfill({ json: { items: definitions, version: '0.1.0' } })
    if (id === 'runtime') {
      return route.fulfill({ json: { domains: {
        newow: status('WAITING', 'ReferenceTrading', { domain_status: 'waiting_archive' }),
        htdy: status('STALE', 'TQKQ simulation monitor', { readback_status: 'stale' }),
        subing: status('UNAVAILABLE', 'PortfolioJournal', { diagnostic: 'SOURCE_TIMEOUT' }),
      } } })
    }
    const strategy = definitions.find(item => item.strategy_id === id)
    const source = strategy.domain === 'newow' ? 'ReferenceTrading' : 'TQKQ simulation monitor'
    if (!resource) {
      return route.fulfill({ json: { strategy, source, capability: { '60m': ['jm', 'rb'], '1d': ['jm'] } } })
    }
    if (resource === 'bindings' && strategy.domain === 'newow') {
      if (firstBusy) {
        firstBusy = false
        return route.fulfill({ json: status('UNAVAILABLE', source, { diagnostic: 'SOURCE_BUSY' }) })
      }
      return route.fulfill({ json: status('NOT_REGISTERED', source, {
        references: [{ kind: 'formula', value: 'newow-formula-test', source }],
      }) })
    }
    if (resource === 'evidence' && strategy.domain === 'newow') {
      return route.fulfill({ json: status('HISTORICAL_RESULT', source, {
        current_publication: 'NOT_PUBLISHED', action_trading_day: '2026-11-27', trade_cutoff: stamp,
        result: { revision_id: 'history-revision', seq: 24 },
        actions: [{ kind: 'BUILD', signal_id: 'saved-action', bar_end: stamp }],
        hints: [{ quantity_effect: 'none', hint_id: 'saved-hint', bar_end: stamp }],
        reference_trades: [],
      }) })
    }
    return route.fulfill({ json: status('NOT_REGISTERED', source) })
  })

  await page.goto('/workstation')
  await page.getByRole('link', { name: '策略中心', exact: true }).click()
  const directory = page.getByLabel('策略目录')
  await expect(directory.getByRole('link')).toHaveCount(6)
  await expect(directory.getByText('读取失败')).toBeVisible()
  await directory.getByRole('link', { name: /双策略融合/ }).click()
  const detail = page.getByLabel('策略详情')
  await expect(detail.getByText('newow-formula-test')).toBeVisible()
  await expect(detail.getByText('waiting_archive', { exact: true })).toBeVisible()
  await expect(detail.getByText('当前盘后凭证尚无已发布结果')).toBeVisible()
  await expect(detail.getByText('saved-action')).toBeVisible()
  await expect(detail.getByText('saved-hint')).toBeVisible()
  await detail.getByLabel('品种').selectOption('rb')
  await expect(detail.getByText('saved-hint')).toBeVisible()
  await directory.getByRole('link', { name: /火天大有 60m/ }).click()
  await expect(detail.getByText(/原始公式有重绘/)).toBeVisible()
  await expect(detail.getByText('原生读回', { exact: true })).toBeVisible()
  expect(seen.every(method => method === 'GET')).toBe(true)
})
