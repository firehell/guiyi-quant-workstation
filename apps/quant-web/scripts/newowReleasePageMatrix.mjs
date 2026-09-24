/** Read-only browser acceptance against two disjoint, exact-policy audit reports. */
import { chromium } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { appendFile, readFile, writeFile } from 'node:fs/promises'

const [frequency, firstReport, secondReport, outputPath] = process.argv.slice(2)
if (!['1d', '1w'].includes(frequency) || !firstReport || !secondReport || !outputPath) {
  throw new Error('NEWOW_PAGE_MATRIX_ARGUMENT_INVALID')
}
const sha = execFileSync('git', ['rev-parse', 'HEAD'], { encoding: 'utf8' }).trim()
const reportInputs = await Promise.all([firstReport, secondReport].map(async file => {
  const raw = await readFile(file, 'utf8')
  return { report: JSON.parse(raw), digest: createHash('sha256').update(raw).digest('hex') }
}))
const reports = reportInputs.map(input => input.report)
const v2 = frequency === '1d' ? 'newow_daily_input_quality_v2' : 'newow_weekly_input_quality_v2'
const sizes = frequency === '1d' ? [50, 10] : [41, 19]
if (reports.some((report, index) => report.code_sha !== sha
    || report.complete !== true || report.readonly !== true
    || report.as_of !== '2026-09-18T07:00:00.000001+00:00'
    || report.release_stage !== 'daily_weekly'
    || JSON.stringify(report.frequency_scope) !== JSON.stringify([frequency])
    || report.product_count !== sizes[index]
    || report.main_case_count !== sizes[index] * 3
    || report.cases?.some(item => item.input_quality_policy !== (index === 0 ? undefined : v2))
    || report.provider_requests !== 0 || report.writes !== 0)) {
  throw new Error('NEWOW_PAGE_MATRIX_AUDIT_INVALID')
}
const cases = reports.flatMap(report => report.cases)
if (cases.length !== 180 || new Set(cases.map(item =>
  `${item.symbol}:${item.strategy}:${item.frequency}`)).size !== 180
  || cases.some(item => item.frequency !== frequency
    || !['READY', 'WARMING'].includes(item.main.status))) {
  throw new Error('NEWOW_PAGE_MATRIX_SCOPE_INVALID')
}
const bases = (process.env.NEWOW_BROWSER_BASE_URLS || 'http://127.0.0.1:5174')
  .split(',').map(value => value.trim()).filter(Boolean)
if (bases.length === 0) throw new Error('NEWOW_PAGE_MATRIX_BROWSER_BASE_EMPTY')
const identities = await Promise.all(bases.map(async base => {
  const response = await fetch(`${base}/api/preview/identity`, {
    cache: 'no-store', signal: AbortSignal.timeout(10_000),
  })
  return response.ok ? response.json() : null
}))
if (identities.some(identity => identity?.mode !== 'local_candidate_readonly'
  || identity?.code_sha !== sha || identity?.realtime !== false)) {
  throw new Error('NEWOW_PAGE_MATRIX_PREVIEW_IDENTITY_INVALID')
}
await writeFile(outputPath, '', { flag: 'wx' })
const browser = await chromium.launch({ channel: 'chrome', headless: true })
let next = 0
let failures = 0
let completed = 0

async function worker(base) {
  while (next < cases.length) {
    const item = cases[next++]
    const started = Date.now()
    const context = await browser.newContext({ viewport: { width: 1440, height: 900 } })
    const page = await context.newPage()
    const expected = item.main.status === 'READY' ? 'ready' : 'warming'
    const row = {
      product: item.symbol, strategy: item.strategy, frequency, code_sha: sha,
      audit_status: item.main.status, expected, chart_state: null,
      reference_summary_visible: false, reference_load: null, error: null,
      elapsed_ms: null,
    }
    try {
      const url = `${base}/market/chart?symbol=${item.symbol}&view=newow`
        + `&strategy=${item.strategy}&frequency=${frequency}&series_kind=actual_dominant`
      await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 30_000 })
      await page.getByTestId('candidate-preview-banner').getByText('身份已核对', {
        exact: false,
      }).waitFor({ timeout: 20_000 })
      const workspace = page.locator('[data-detail-workspace="newow"]')
      await page.waitForFunction(() => {
        const state = document.querySelector('[data-detail-workspace="newow"]')
          ?.getAttribute('data-chart-state')
        return state && !['not_requested', 'loading', 'idle', 'pending'].includes(state)
      }, {}, { timeout: 120_000 })
      row.chart_state = await workspace.getAttribute('data-chart-state')
      if (row.chart_state !== expected) throw new Error('CHART_STATE_MISMATCH')
      await page.getByRole('button', { name: '参考记录', exact: true }).click()
      const summary = page.getByTestId('newow-reference-summary')
      if (expected === 'warming') {
        // A warming chart may defer reference work until this explicit action.
        const load = page.getByRole('button', { name: '读取参考交易', exact: true })
        if (await load.isVisible().catch(() => false)) {
          await load.click()
          row.reference_load = 'explicit'
        } else {
          row.reference_load = 'automatic'
        }
      } else {
        row.reference_load = 'automatic'
      }
      await summary.waitFor({ timeout: 120_000 })
      const summaryText = (await summary.innerText()).trim()
      row.reference_summary_visible = Boolean(summaryText)
      if (!row.reference_summary_visible) throw new Error('REFERENCE_SUMMARY_EMPTY')
      if (expected === 'warming' && !summaryText.includes('预热')) {
        throw new Error('REFERENCE_WARMING_STATUS_MISMATCH')
      }
    } catch (error) {
      row.error = String(error?.message || error).slice(0, 400)
      failures += 1
    } finally {
      row.elapsed_ms = Date.now() - started
      completed += 1
      await appendFile(outputPath, `${JSON.stringify(row)}\n`)
      await context.close()
    }
  }
}
try {
  await Promise.all(bases.map(worker))
} finally {
  await browser.close()
}
console.log(JSON.stringify({ frequency, code_sha: sha, cases: cases.length, completed,
  failures, audit_sha256: reportInputs.map(input => input.digest), outputPath }))
if (failures || completed !== 180) process.exitCode = 1
