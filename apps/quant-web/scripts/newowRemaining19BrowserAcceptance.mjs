import { chromium } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import path from 'node:path'

const PRODUCTS = 'b bz cj eb eg j oi pf pg pk pl pr px rs sf sh si sm sr'.split(' ')
const STRATEGIES = ['trend', 'oscillation', 'main_rise']
const CASES = PRODUCTS.flatMap(product => STRATEGIES.map(strategy => ({ product, strategy })))
const BASE_URL = process.env.NEWOW_BROWSER_BASE_URL || 'http://127.0.0.1:5174'
const CODE_SHA = execFileSync('git', ['rev-parse', 'HEAD'], { encoding: 'utf8' }).trim()
const PAGE_STATE_BY_STATUS = new Map([
  ['READY', 'ready'],
  ['DATA_UNAVAILABLE', 'unavailable'],
  ['INTEGRITY_ERROR', 'unavailable'],
  ['SOURCE_EXCEPTION', 'unavailable'],
])
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
  {
    status: item.main.status,
    reason: item.main.reason ?? null,
    apiCode: item.main.error?.code ?? null,
    pageState: PAGE_STATE_BY_STATUS.get(item.main.status) ?? null,
    qualityPolicy: item.input_quality_policy,
    ready: item.main.status === 'READY',
  },
]))
if (
  !/^[0-9a-f]{40}$/.test(CODE_SHA)
  || expected.size !== CASES.length
  || [...expected.values()].some(item => (
    item.pageState === null
    || item.qualityPolicy !== 'newow_weekly_input_quality_v2'
    || (item.ready ? item.apiCode !== null || item.reason !== null : item.apiCode === null || item.reason === null)
  ))
) throw new Error('BROWSER_ACCEPTANCE_MATRIX_INVALID')

const results = []
let browser = null
let fatal = null
let previewIdentity = null

try {
  const identityResponse = await fetch(new URL('/api/preview/identity', BASE_URL), {
    cache: 'no-store',
    signal: AbortSignal.timeout(10_000),
  })
  previewIdentity = await identityResponse.json()
  if (
    !identityResponse.ok
    || previewIdentity?.mode !== 'local_candidate_readonly'
    || previewIdentity?.code_sha !== CODE_SHA
    || previewIdentity?.default_weekly !== true
    || previewIdentity?.as_of !== null
    || previewIdentity?.realtime !== false
    || previewIdentity?.candidate_origin !== 'http://127.0.0.1:8010'
  ) throw new Error('BROWSER_ACCEPTANCE_PREVIEW_IDENTITY_INVALID')
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
      if (url.pathname.endsWith('/strategy-detail') || url.pathname.endsWith('/weekly-snapshot')) {
        requests.push({
          endpoint: url.pathname.endsWith('/weekly-snapshot') ? 'weekly_snapshot' : 'strategy_detail',
          section: url.searchParams.get('section'),
          asOf: url.searchParams.get('as_of'),
          url: request.url(),
        })
      }
    })
    page.on('response', response => {
      const url = new URL(response.url())
      if (!url.pathname.endsWith('/strategy-detail') && !url.pathname.endsWith('/weekly-snapshot')) return
      responseTasks.push((async () => {
        let body = null
        try { body = await response.json() } catch { /* bounded non-JSON evidence */ }
        responses.push({
          endpoint: url.pathname.endsWith('/weekly-snapshot') ? 'weekly_snapshot' : 'strategy_detail',
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
      if (expectation.ready) {
        await page.locator(
          '[data-detail-workspace="newow"][data-chart-state="ready"]',
        ).waitFor({ state: 'visible', timeout: 120_000 })
      } else {
        await page.locator(
          '[data-detail-workspace="newow"]:not([data-chart-state="loading"]):not([data-chart-state="not_requested"])',
        ).waitFor({ state: 'visible', timeout: 120_000 })
      }
      await page.waitForTimeout(250)
      await Promise.allSettled(responseTasks)
      const bannerText = await banner.innerText()
      const chartState = await workspace.getAttribute('data-chart-state')
      const unavailableVisible = await page.getByText('主图事实不可用', { exact: true }).isVisible()
      const chartResponse = responses.find(item => item.endpoint === 'strategy_detail' && item.section === 'chart')
      const snapshotResponse = responses.find(item => item.endpoint === 'weekly_snapshot')
      const stateResponse = expectation.ready
        ? chartResponse
        : (chartResponse ?? snapshotResponse)
      const apiReason = expectation.ready
        ? (stateResponse?.body?.status?.reason ?? null)
        : (stateResponse?.body?.detail?.diagnostic?.reason ?? null)
      const apiCode = expectation.ready
        ? (stateResponse?.body?.detail?.code ?? null)
        : (stateResponse?.body?.detail?.code ?? null)
      const defaultAsOfAbsent = expectation.ready
        ? requests
          .filter(item => item.endpoint === 'weekly_snapshot')
          .every(item => item.asOf === null)
          && requests.some(item => item.endpoint === 'weekly_snapshot')
        : requests.length > 0 && requests.every(item => item.asOf === null)
      const responseMatches = expectation.ready
        ? stateResponse !== undefined
          && stateResponse.status === 200
          && stateResponse.body?.chart?.status?.status === 'ready'
          && apiCode === null
          && !unavailableVisible
        : stateResponse !== undefined
          && stateResponse.status === 409
          && apiCode === expectation.apiCode
          && apiReason === expectation.reason
          && unavailableVisible
      const pagePass = navigation?.status() === 200
        && bannerText.includes('身份已核对')
        && bannerText.includes(`代码 ${CODE_SHA}`)
        && bannerText.includes('周线按当前完整周只读解析')
        && bannerText.includes('127.0.0.1:8010')
        && chartState === expectation.pageState
        && responseMatches
        && expectation.qualityPolicy === 'newow_weekly_input_quality_v2'
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
        pageStateSource: chartResponse !== undefined ? 'strategy_detail' : 'weekly_snapshot',
        apiStatus: stateResponse?.status ?? null,
        apiCode,
        apiReason,
        codeSha: CODE_SHA,
        expectedStatus: expectation.status,
        expectedPageState: expectation.pageState,
        expectedApiCode: expectation.apiCode,
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
    codeSha: CODE_SHA,
    previewIdentity,
    matrixCodeSha: matrix.audit_identity?.code_sha ?? null,
    catalogRevision: matrix.audit_identity?.catalog_revision_after ?? null,
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
