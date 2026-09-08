import { expect, test } from '@playwright/test'
import { installNewowProductFixtures, newowRoute, NEWOW_AS_OF } from './newow-product.helpers.mjs'
import { execFileSync } from 'node:child_process'

test.skip(process.env.PLAYWRIGHT_CANDIDATE_PREVIEW !== '1', 'explicit isolated preview fixture only')

test('preview identifies both sources, fixes cutoff and never subscribes to live even with overrides', async ({ page }) => {
  const requests = []
  const sockets = []
  page.on('request', request => requests.push(request.url()))
  page.on('websocket', socket => sockets.push(socket.url()))
  await installNewowProductFixtures(page, { frozenNow: '2026-09-07T08:00:00.000Z' })
  await page.route('**/api/preview/identity', route => route.fulfill({ json: {
    mode: 'local_candidate_readonly', code_sha: execFileSync('git', ['rev-parse', 'HEAD'], { encoding: 'utf8' }).trim(),
    as_of: NEWOW_AS_OF, realtime: false,
    candidate_origin: 'http://127.0.0.1:8010', status_origin: 'http://127.0.0.1:8000',
  } }))
  await page.goto(newowRoute('trend', '60m'))
  await expect(page.getByTestId('candidate-preview-banner')).toContainText('本地候选只读预览')
  await expect(page.getByTestId('candidate-preview-banner')).toContainText('非实时')
  await expect(page.getByTestId('candidate-preview-banner')).toContainText('8010')
  await expect(page.getByTestId('candidate-preview-banner')).toContainText('8000')
  await expect(page.getByTestId('candidate-preview-banner')).toContainText('首页投影与主力元数据使用各自时间戳')
  await expect(page.getByTestId('newow-product-chart-stage')).toHaveAttribute('data-auxiliary-state', 'ready')
  const strategy = requests.filter(url => url.includes('/newow/strategy-detail'))
  expect(strategy.length).toBeGreaterThan(0)
  expect(strategy.every(url => new URL(url).searchParams.get('as_of') === NEWOW_AS_OF)).toBe(true)
  expect(requests.every(url => new URL(url).origin === 'http://127.0.0.1:5182')).toBe(true)
  expect(requests.filter(url => url.includes('/market/state'))).toEqual([])
  expect(sockets.filter(url => !url.includes('token='))).toEqual([])
  expect(await page.evaluate(() => new Date().toISOString())).toBe('2026-09-07T08:00:00.000Z')
  expect(await page.evaluate(() => window.__newowFixtureWebSockets.every(value => {
    const url = new URL(value)
    return url.origin === 'ws://127.0.0.1:5182' && url.pathname === '/' && url.searchParams.has('token')
  }))).toBe(true) // Only Vite's local HMR socket is permitted; never a market subscription.
})

test('identity mismatch blocks candidate page queries', async ({ page }) => {
  const requests = []
  page.on('request', request => requests.push(request.url()))
  await installNewowProductFixtures(page)
  await page.route('**/api/preview/identity', route => route.fulfill({ json: { code_sha: 'wrong' } }))
  await page.goto(newowRoute())
  await expect(page.getByTestId('candidate-preview-banner')).toContainText('PREVIEW_IDENTITY_MISMATCH')
  expect(requests.filter(url => url.includes('/api/v1/market/'))).toEqual([])
})

test('fixture server rejects management and ambiguous paths before any upstream access', async ({ request }) => {
  for (const [method, path] of [['POST', '/api/runtime/health'], ['DELETE', '/api/alerts/current-events?limit=30'],
    ['GET', '/api/runtime/health/'], ['GET', '/api/runtime/%68ealth'],
    ['GET', '/api/alerts/rules'], ['GET', '/api/alerts/current-events?limit=31'],
    ['GET', '/api/v1/market/state'], ['GET', '/ws/market']]) {
    const response = await request.fetch(path, { method })
    expect(response.status()).toBe(403)
    expect(await response.json()).toEqual({ detail: { code: 'PREVIEW_ROUTE_FORBIDDEN' } })
  }
})
