import { chromium } from '@playwright/test'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import path from 'node:path'

const PRODUCTS = 'b bz cj eb eg j oi pf pg pk pl pr px rs sf sh si sm sr'.split(' ')
const STRATEGIES = ['trend', 'oscillation', 'main_rise']
const CASES = PRODUCTS.flatMap(product => STRATEGIES.map(strategy => ({ product, strategy })))
const BASE_URL = process.env.NEWOW_BROWSER_BASE_URL || 'http://127.0.0.1:5174'
const outputRoot = process.argv[2]
const matrixPath = process.argv[3]
if (!outputRoot || !matrixPath) throw new Error('BROWSER_ACCEPTANCE_ARGUMENT_INVALID')

await mkdir(outputRoot, { recursive: true })
const outputPath = path.join(outputRoot, 'browser-cases.jsonl')
const summaryPath = path.join(outputRoot, 'browser-summary.json')
await writeFile(outputPath, '')
const matrix = JSON.parse(await readFile(matrixPath, 'utf8'))
const expected = new Map(matrix.cases.map(item => [
  `${item.symbol}:${item.strategy}`,
  { status: item.main.status, reason: item.main.reason, qualityPolicy: item.input_quality_policy },
]))
if (expected.size !== CASES.length) throw new Error('BROWSER_ACCEPTANCE_MATRIX_INVALID')

const results = []
let browser = null
let fatal = null

try {
  browser = await chromium.launch({ channel: 'chrome', headless: true })
  for (let index = 0; index < CASES.length; index += 1) {
    const { product, strategy } = CASES[index]
    const expectation = expected.get(`${product}:${strategy}`)
    const started = Date.now()
    const context = await browser.newContext({ viewport: { width: 1440, height: 900 } })
    const page = await context.newPage()
    const pageErrors = []
    const consoleErrors = []
    const requests = []
    const responses = []
    const responseTasks = []
    page.on('pageerror', error => pageErrors.push(error.message))
    page.on('console', message => {
      if (message.type() === 'error') consoleErrors.push(message.text())
    })
    page.on('request', request => {
      const url = new URL(request.url())
      if (url.pathname.endsWith('/strategy-detail')) {
        requests.push({
          section: url.searchParams.get('section'),
          asOf: url.searchParams.get('as_of'),
          url: request.url(),
        })
      }
    })
    page.on('response', response => {
      const url = new URL(response.url())
      if (!url.pathname.endsWith('/strategy-detail')) return
      responseTasks.push((async () => {
        let body = null
        try { body = await response.json() } catch { /* bounded non-JSON evidence */ }
        responses.push({
          section: url.searchParams.get('section'),
          status: response.status(),
          body,
        })
      })())
    })

    let result
    try {
      const url = `${BASE_URL}/market/chart?symbol=${product}&view=newow&strategy=${strategy}&series_kind=actual_dominant&frequency=1w`
      const navigation = await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 30_000 })
      const banner = page.getByTestId('candidate-preview-banner')
      await banner.waitFor({ state: 'visible', timeout: 15_000 })
      const workspace = page.locator('[data-detail-workspace="newow"]')
      await workspace.waitFor({ state: 'visible', timeout: 30_000 })
      await page.locator(
        '[data-detail-workspace="newow"]:not([data-chart-state="loading"]):not([data-chart-state="not_requested"])',
      ).waitFor({ state: 'visible', timeout: 120_000 })
      await page.waitForTimeout(250)
      await Promise.allSettled(responseTasks)
      const bannerText = await banner.innerText()
      const chartState = await workspace.getAttribute('data-chart-state')
      const unavailableVisible = await page.getByText('主图事实不可用', { exact: true }).isVisible()
      const chartResponse = responses.find(item => item.section === 'chart')
      const apiReason = chartResponse?.body?.detail?.diagnostic?.reason ?? null
      const apiCode = chartResponse?.body?.detail?.code ?? null
      const defaultAsOfAbsent = requests.length > 0 && requests.every(item => item.asOf === null)
      const pagePass = navigation?.status() === 200
        && bannerText.includes('身份已核对')
        && bannerText.includes('周线按当前完整周只读解析')
        && bannerText.includes('127.0.0.1:8010')
        && chartState !== null && !['loading', 'not_requested'].includes(chartState)
        && unavailableVisible
        && chartResponse !== undefined
        && apiReason === expectation.reason
        && defaultAsOfAbsent
        && pageErrors.length === 0
      result = {
        index,
        product,
        strategy,
        terminal: 'completed',
        pagePass,
        navigationStatus: navigation?.status() ?? null,
        chartState,
        unavailableVisible,
        apiStatus: chartResponse?.status ?? null,
        apiCode,
        apiReason,
        expectedStatus: expectation.status,
        expectedReason: expectation.reason,
        inputQualityPolicy: expectation.qualityPolicy,
        defaultAsOfAbsent,
        requestCount: requests.length,
        responseCount: responses.length,
        pageErrors,
        consoleErrors,
        elapsedMs: Date.now() - started,
      }
    } catch (error) {
      await Promise.allSettled(responseTasks)
      result = {
        index,
        product,
        strategy,
        terminal: 'interrupted',
        pagePass: false,
        error: String(error),
        expectedStatus: expectation.status,
        expectedReason: expectation.reason,
        inputQualityPolicy: expectation.qualityPolicy,
        requestCount: requests.length,
        responseCount: responses.length,
        pageErrors,
        consoleErrors,
        elapsedMs: Date.now() - started,
      }
    } finally {
      await context.close()
    }
    results.push(result)
    await writeFile(outputPath, `${results.map(item => JSON.stringify(item)).join('\n')}\n`)
    process.stdout.write(`${results.length}/${CASES.length} ${product}/${strategy} ${result.pagePass ? 'PAGE_PASS' : result.terminal.toUpperCase()}\n`)
  }
} catch (error) {
  fatal = String(error)
} finally {
  if (browser !== null) await browser.close()
  const completedKeys = new Set(results.map(item => `${item.product}:${item.strategy}`))
  const untested = CASES.filter(item => !completedKeys.has(`${item.product}:${item.strategy}`))
  const summary = {
    schemaVersion: 'newow_remaining19_browser_acceptance_v1',
    baseURL: BASE_URL,
    denominator: CASES.length,
    completed: results.length,
    pagePass: results.filter(item => item.pagePass).length,
    interrupted: results.filter(item => item.terminal === 'interrupted').length,
    untested: untested.length,
    fatal,
    untestedCases: untested,
    results,
  }
  await writeFile(summaryPath, `${JSON.stringify(summary, null, 2)}\n`)
  console.log(JSON.stringify({
    denominator: summary.denominator,
    completed: summary.completed,
    pagePass: summary.pagePass,
    interrupted: summary.interrupted,
    untested: summary.untested,
    fatal: summary.fatal,
  }))
  if (summary.pagePass !== CASES.length || summary.interrupted || summary.untested || fatal) {
    process.exitCode = 1
  }
}
