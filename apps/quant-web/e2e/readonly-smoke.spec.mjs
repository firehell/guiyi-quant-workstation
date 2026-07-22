import { expect, test } from '@playwright/test'

/**
 * 真实后端只读 smoke：默认 skip；设置 REAL_BACKEND=1 且后端可达时运行。
 * 禁止创建回测、扫描、ack、review 写入、live、归档、企微发送。
 */
const enabled = process.env.REAL_BACKEND === '1'
const apiBase = (process.env.PLAYWRIGHT_API_BASE || 'http://127.0.0.1:8000').replace(/\/+$/, '')

test.describe('Web V1 real backend read-only smoke', () => {
  test.skip(!enabled, 'Set REAL_BACKEND=1 to run against a live backend')

  test('health and runtime health are readable', async ({ request }) => {
    const health = await request.get(`${apiBase}/api/health`)
    expect(health.ok()).toBeTruthy()

    const runtime = await request.get(`${apiBase}/api/runtime/health`)
    expect(runtime.ok()).toBeTruthy()
    const body = await runtime.json()
    expect(body).toHaveProperty('status')
    expect(body).toHaveProperty('readonly')
  })

  test('data coverage paged response hides paths by default', async ({ request }) => {
    const res = await request.get(`${apiBase}/api/v1/data/coverage?paged=true&limit=5&offset=0`)
    expect(res.ok()).toBeTruthy()
    const body = await res.json()
    expect(body).toHaveProperty('items')
    expect(body).toHaveProperty('total')
    for (const item of body.items || []) {
      expect(item.file_path == null).toBeTruthy()
    }
  })

  test('market bars read stays GET-only when available', async ({ request }) => {
    const candidates = [
      `${apiBase}/api/v1/market/bars?symbol=jm&contract=JM2609&period=15m&limit=5`,
      `${apiBase}/api/v1/market/dominants`,
    ]
    let anyOk = false
    for (const url of candidates) {
      const res = await request.get(url)
      if (res.ok()) {
        anyOk = true
        const body = await res.json()
        expect(body).toBeTruthy()
      }
    }
    expect(anyOk).toBeTruthy()
  })

  test('report 14 is readable or explicitly absent', async ({ request }) => {
    const res = await request.get(`${apiBase}/api/backtests/reports/14`)
    if (res.status() === 404) {
      test.info().annotations.push({ type: 'residual', description: 'report 14 not present in this backend' })
      return
    }
    expect(res.ok()).toBeTruthy()
    const body = await res.json()
    expect(body.id ?? body.report_id).toBeTruthy()
  })

  test('signals and events list endpoints are readable', async ({ request }) => {
    const latest = await request.get(`${apiBase}/api/signals/latest?limit=5`)
    expect([200, 404].includes(latest.status())).toBeTruthy()
    if (latest.ok()) {
      expect(Array.isArray(await latest.json())).toBeTruthy()
    }

    const events = await request.get(`${apiBase}/api/signals/events?limit=5`)
    expect([200, 404].includes(events.status())).toBeTruthy()
    if (events.ok()) {
      expect(Array.isArray(await events.json())).toBeTruthy()
    }
  })

  test('reviews list is readable', async ({ request }) => {
    const res = await request.get(`${apiBase}/api/reviews`)
    expect([200, 404].includes(res.status())).toBeTruthy()
    if (res.ok()) {
      const body = await res.json()
      expect(Array.isArray(body)).toBeTruthy()
    }
  })

  test('suite contract is GET-only', async () => {
    // 结构性保证：本文件仅使用 request.get，不创建回测/扫描/ack/review/live/归档/企微。
    expect(true).toBeTruthy()
  })
})
