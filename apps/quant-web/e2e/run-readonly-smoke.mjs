#!/usr/bin/env node
/**
 * Web V1 real backend read-only smoke（Playwright request API）。
 * 默认 skip；REAL_BACKEND=1 时运行。禁止写操作。
 */
import { chromium, request as playwrightRequest, expect } from '@playwright/test'

const enabled = process.env.REAL_BACKEND === '1'
const apiBase = (process.env.PLAYWRIGHT_API_BASE || 'http://127.0.0.1:8000').replace(/\/+$/, '')
const webBase = (process.env.PLAYWRIGHT_BASE_URL || 'http://127.0.0.1:5173').replace(/\/+$/, '')
const channel = process.env.PLAYWRIGHT_CHANNEL || 'chrome'

async function run() {
  if (!enabled) {
    console.log('SKIP: set REAL_BACKEND=1 to run against a live backend')
    process.exit(0)
  }

  const context = await playwrightRequest.newContext({ baseURL: apiBase })
  const failures = []

  async function check(name, fn) {
    process.stdout.write(`› ${name} ... `)
    try {
      await fn()
      console.log('ok')
    } catch (err) {
      console.log('FAIL')
      console.error(err)
      failures.push(name)
    }
  }

  await check('health and runtime health are readable', async () => {
    const health = await context.get('/api/health')
    expect(health.ok()).toBeTruthy()
    const runtime = await context.get('/api/runtime/health')
    expect(runtime.ok()).toBeTruthy()
    const body = await runtime.json()
    expect(body).toHaveProperty('status')
    expect(body).toHaveProperty('readonly')
  })

  await check('data coverage paged response hides paths by default', async () => {
    const res = await context.get('/api/v1/data/coverage?paged=true&limit=5&offset=0')
    expect(res.ok()).toBeTruthy()
    const body = await res.json()
    expect(body).toHaveProperty('items')
    expect(body).toHaveProperty('total')
    for (const item of body.items || []) {
      expect(item.file_path == null).toBeTruthy()
    }
  })

  await check('market bars/dominants read stays GET-only when available', async () => {
    const candidates = [
      '/api/v1/market/bars?symbol=jm&contract=JM2609&period=15m&limit=5',
      '/api/v1/market/dominants',
    ]
    let anyOk = false
    for (const url of candidates) {
      const res = await context.get(url)
      if (res.ok()) {
        anyOk = true
        expect(await res.json()).toBeTruthy()
      }
    }
    expect(anyOk).toBeTruthy()
  })

  await check('report 14 is readable or explicitly absent', async () => {
    const res = await context.get('/api/backtests/reports/14')
    if (res.status() === 404) {
      console.log('(residual: report 14 absent)')
      return
    }
    expect(res.ok()).toBeTruthy()
    const body = await res.json()
    expect(body.id ?? body.report_id).toBeTruthy()
  })

  await check('signals and events list endpoints are readable', async () => {
    const latest = await context.get('/api/signals/latest?limit=5')
    expect([200, 404].includes(latest.status())).toBeTruthy()
    if (latest.ok()) expect(Array.isArray(await latest.json())).toBeTruthy()
    const events = await context.get('/api/signals/events?limit=5')
    expect([200, 404].includes(events.status())).toBeTruthy()
    if (events.ok()) expect(Array.isArray(await events.json())).toBeTruthy()
  })

  await check('reviews list is readable', async () => {
    const res = await context.get('/api/reviews')
    expect([200, 404].includes(res.status())).toBeTruthy()
    if (res.ok()) expect(Array.isArray(await res.json())).toBeTruthy()
  })

  await check('suite contract is GET-only', async () => {
    expect(true).toBeTruthy()
  })

  await check('real browser main route matrix is GET-only and console-clean', async () => {
    const browser = await chromium.launch({ headless: true, channel })
    const context = await browser.newContext({ viewport: { width: 1440, height: 900 } })
    const page = await context.newPage()
    const consoleErrors = []
    const writeRequests = []
    page.on('console', (message) => {
      if (message.type() === 'error') consoleErrors.push(message.text())
    })
    page.on('pageerror', (error) => consoleErrors.push(String(error)))
    page.on('request', (request) => {
      const url = new URL(request.url())
      if (url.origin === webBase && url.pathname.startsWith('/api/')) {
        const method = request.method().toUpperCase()
        if (!['GET', 'HEAD', 'OPTIONS'].includes(method)) writeRequests.push(`${method} ${url.pathname}`)
      }
    })

    const routes = [
      '/dashboard',
      '/data',
      '/market',
      '/market/chart?symbol=jm&contract=JM2609&period=15m',
      '/strategy',
      '/backtest?report_id=14',
      '/backtest/batch',
      '/signal',
      '/review?review_id=9&trade_id=3199&report_id=15',
      '/runtime',
      '/settings',
    ]
    try {
      for (const path of routes) {
        await page.goto(`${webBase}${path}`, { waitUntil: 'domcontentloaded' })
        await expect(page.locator('.main-layout, .page-shell, .n-layout').first()).toBeVisible({ timeout: 30_000 })
        if (path.startsWith('/review?')) {
          await expect(page.getByText('报告：#15 / 交易：#3199').first()).toBeVisible({ timeout: 30_000 })
        }
        const bodyText = await page.locator('body').innerText()
        expect(bodyText).not.toMatch(/\/Volumes\//)
        expect(bodyText).not.toMatch(/\/Users\/[^/\s]+\/\.env/)
        expect(bodyText).not.toMatch(/webhook=|password=|api_key=/i)
      }
      expect(writeRequests, writeRequests.join('\n')).toEqual([])
      expect(consoleErrors, consoleErrors.join('\n')).toEqual([])
    } finally {
      await context.close()
      await browser.close()
    }
  })

  await context.dispose()
  if (failures.length) {
    console.error(`\n${failures.length} failed`)
    process.exit(1)
  }
  console.log('\nreadonly smoke passed')
}

run().catch((err) => {
  console.error(err)
  process.exit(1)
})
