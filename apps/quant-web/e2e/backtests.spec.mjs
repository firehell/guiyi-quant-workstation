import { expect, test } from '@playwright/test'

const API_BASE = 'http://127.0.0.1:8011/api/v1/backtests'
const RUN_ID = '019d2345-67ab-7def-8123-456789abcdef'
const SECOND_RUN_ID = '019d2345-67ab-7def-8123-456789abcdee'
const PNG_1PX = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Y9Z4WQAAAAASUVORK5CYII=',
  'base64',
)

function readyHealth(overrides = {}) {
  return {
    status: 'ready',
    research_only: true,
    formal_evidence: false,
    promotion_eligible: false,
    busy: false,
    runner: {
      available: true,
      rqalpha_version: '5.6.0',
      rqsdk_version: '2.8.0',
      python_version: '3.13.5',
    },
    bundle_available: true,
    runs_root_available: true,
    registry_available: true,
    error: null,
    ...overrides,
  }
}

function strategy() {
  return {
    id: 'example_future_smoke_v1',
    name: '期货回测链路示例',
    description: '只用于验证本机 RQAlpha 回测链路',
    supported_frequencies: ['1d', '1m'],
    defaults: {
      future_cash: '1000000',
      matching_type: 'current_bar',
      margin_multiplier: '1',
      futures_commission_multiplier: '1',
      slippage_model: 'PriceRatioSlippage',
      slippage: '0',
    },
    parameters: [
      { name: 'lookback', type: 'integer', default: 20, minimum: 2, maximum: 120, options: [] },
      { name: 'threshold', type: 'decimal', default: '0.25', minimum: '0', maximum: '1', options: [] },
      { name: 'long_only', type: 'boolean', default: true, minimum: null, maximum: null, options: [] },
      { name: 'contract', type: 'enum', default: 'RB2610', minimum: null, maximum: null, options: ['RB2610', 'HC2610'] },
    ],
    research_only: true,
    formal_evidence: false,
    promotion_eligible: false,
  }
}

function requestedConfig() {
  return {
    strategy_id: 'example_future_smoke_v1',
    start_date: '2026-01-01',
    end_date: '2026-01-31',
    frequency: '1d',
    future_cash: '1000000',
    matching_type: 'current_bar',
    margin_multiplier: '1',
    futures_commission_multiplier: '1',
    slippage_model: 'PriceRatioSlippage',
    slippage: '0',
    parameters: { lookback: 20, threshold: '0.25', long_only: true, contract: 'RB2610' },
  }
}

function runSummary(status = 'succeeded', overrides = {}) {
  return {
    run_id: RUN_ID,
    research_only: true,
    formal_evidence: false,
    promotion_eligible: false,
    strategy_id: 'example_future_smoke_v1',
    strategy_name: '期货回测链路示例',
    strategy_entry_file: 'example_future_smoke_v1.py',
    strategy_sha256: 'a'.repeat(64),
    repository_commit: '920d79392fc62a30e7e1e1fffd6ece93edd939a6',
    bundle_path: '/configured/read-only/bundle',
    versions: { rqalpha: '5.6.0', rqsdk: '2.8.0', python: '3.13.5' },
    requested_config: requestedConfig(),
    effective_config: {
      base: { data_bundle_path: '/configured/read-only/bundle', auto_update_bundle: false },
      mod: { sys_analyser: { plot: true } },
    },
    effective_parameters: { lookback: 20, threshold: '0.25', long_only: true, contract: 'RB2610' },
    status,
    started_at: '2026-08-23T01:00:00Z',
    finished_at: status === 'running' ? null : '2026-08-23T01:00:07Z',
    exit_code: status === 'succeeded' ? 0 : null,
    failure_code: null,
    ...overrides,
  }
}

function runDetail(status = 'succeeded', overrides = {}) {
  return {
    ...runSummary(status),
    result: status === 'succeeded' ? {
      summary: {
        total_returns: '0.125',
        annualized_returns: '0.42',
        max_drawdown: '-0.031',
        sharpe: '1.82',
        sortino: '2.11',
        volatility: '0.18',
        total_value: '1125000',
        cash: '425000',
      },
      equity: [
        { date: '2026-01-02', unit_net_value: '1.0' },
        { date: '2026-01-30', unit_net_value: '1.125' },
      ],
      trade_count: '8',
      artifacts: {
        report_zip: true,
        result_pickle: true,
        equity_png: true,
        stdout_log: true,
        stderr_log: true,
        run_json: true,
      },
    } : null,
    stdout_tail: status === 'running' ? 'runner is working' : 'runner completed safely',
    stderr_tail: status === 'running' ? '' : 'research warning only',
    ...overrides,
  }
}

async function mockBacktestApi(page, options = {}) {
  const detailResponsesByRunId = {
    [RUN_ID]: [...(options.detailResponses || [runDetail()])],
    ...(options.detailResponsesByRunId || {}),
  }
  const store = {
    requests: [],
    postBodies: [],
    healthCalls: 0,
    runCalls: 0,
    completedRunCalls: 0,
    detailCalls: 0,
    detailCallsByRunId: {},
    healthResponses: [...(options.healthResponses || [readyHealth()])],
    runResponses: [...(options.runResponses || [options.runs || []])],
    detailResponsesByRunId,
  }

  await page.route(`${API_BASE}/**`, async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    const path = url.pathname
    const method = request.method()
    const corsHeaders = {
      'access-control-allow-origin': '*',
      'access-control-allow-methods': 'GET,POST,OPTIONS',
      'access-control-allow-headers': 'content-type',
    }

    if (method === 'OPTIONS') {
      return route.fulfill({ status: 204, headers: corsHeaders })
    }

    store.requests.push(`${method} ${url.pathname}${url.search}`)
    if (method === 'GET' && path.endsWith('/health')) {
      let response = store.healthResponses[Math.min(store.healthCalls, store.healthResponses.length - 1)]
      store.healthCalls += 1
      response = await resolveRouteResponse(response)
      if (response instanceof Error) {
        return route.fulfill({
          status: 503,
          headers: corsHeaders,
          json: { detail: { code: 'BACKTEST_LOCAL_UNAVAILABLE' } },
        })
      }
      return route.fulfill({ headers: corsHeaders, json: response })
    }
    if (method === 'GET' && path.endsWith('/strategies')) {
      return route.fulfill({ headers: corsHeaders, json: [strategy()] })
    }
    if (method === 'GET' && path.endsWith('/runs')) {
      let response = store.runResponses[Math.min(store.runCalls, store.runResponses.length - 1)]
      store.runCalls += 1
      response = await resolveRouteResponse(response)
      store.completedRunCalls += 1
      return route.fulfill({ headers: corsHeaders, json: response })
    }
    if (method === 'POST' && path.endsWith('/runs')) {
      store.postBodies.push(request.postDataJSON())
      return route.fulfill({ status: 202, headers: corsHeaders, json: options.startResponse || runSummary('running') })
    }
    const detailMatch = method === 'GET' ? path.match(/\/runs\/([^/]+)$/) : null
    if (detailMatch) {
      const runId = decodeURIComponent(detailMatch[1])
      const responses = store.detailResponsesByRunId[runId]
      if (!responses) {
        return route.fulfill({ status: 404, headers: corsHeaders, json: { detail: { code: 'BACKTEST_RUN_NOT_FOUND' } } })
      }
      const calls = store.detailCallsByRunId[runId] || 0
      let response = responses[Math.min(calls, responses.length - 1)]
      store.detailCalls += 1
      store.detailCallsByRunId[runId] = calls + 1
      response = await resolveRouteResponse(response)
      return route.fulfill({ headers: corsHeaders, json: response })
    }
    if (method === 'GET' && path.includes(`/runs/${RUN_ID}/artifacts/`)) {
      const kind = path.split('/').at(-1)
      const errorCode = options.artifactErrors?.[kind]
      if (errorCode) {
        return route.fulfill({
          status: 404,
          headers: corsHeaders,
          json: { detail: { code: errorCode, message: '/configured/secret must not render' } },
        })
      }
      if (kind === 'equity_png') {
        return route.fulfill({ headers: { ...corsHeaders, 'content-type': 'image/png' }, body: PNG_1PX })
      }
      return route.fulfill({
        headers: { ...corsHeaders, 'content-type': 'application/octet-stream' },
        body: `artifact:${kind}`,
      })
    }
    return route.fulfill({ status: 404, headers: corsHeaders, json: { detail: { code: 'BACKTEST_RUN_NOT_FOUND' } } })
  })

  return store
}

function deferredResponse() {
  let resolve
  const promise = new Promise((next) => { resolve = next })
  return { promise, resolve }
}

async function resolveRouteResponse(response) {
  return typeof response === 'function' ? response() : response
}

test('local ready page renders the registered form, recent terminal detail, and fixed artifacts', async ({ page }) => {
  const store = await mockBacktestApi(page, { runs: [runSummary()] })
  await page.addInitScript(() => {
    window.__revokedBacktestBlobUrls = []
    const revoke = URL.revokeObjectURL.bind(URL)
    URL.revokeObjectURL = (value) => {
      window.__revokedBacktestBlobUrls.push(value)
      revoke(value)
    }
  })

  await page.goto('/backtests')

  await expect(page.getByRole('menuitem', { name: 'RQAlpha 回测' })).toBeVisible()
  await expect(page.getByTestId('backtest-form')).toBeVisible()
  await expect(page.getByText('本机研究工具·不是正式证据')).toBeVisible()
  await expect(page.getByText('回看周期')).toBeVisible()
  await expect(page.getByText('阈值')).toBeVisible()
  await expect(page.getByText('仅做多')).toBeVisible()
  await expect(page.getByText('回测合约')).toBeVisible()
  await expect(page.getByRole('combobox', { name: '策略' })).toBeVisible()
  await expect(page.getByRole('combobox', { name: '频率' })).toBeVisible()
  await expect(page.getByLabel('开始日期')).toBeVisible()
  await expect(page.getByLabel('结束日期')).toBeVisible()
  await expect(page.getByRole('textbox', { name: '期货初始资金' })).toBeVisible()
  await expect(page.getByRole('combobox', { name: '撮合方式' })).toBeVisible()
  await expect(page.getByRole('textbox', { name: '保证金倍数' })).toBeVisible()
  await expect(page.getByRole('textbox', { name: '期货手续费倍数' })).toBeVisible()
  await expect(page.getByRole('combobox', { name: '滑点模型' })).toBeVisible()
  await expect(page.getByRole('textbox', { name: '滑点' })).toBeVisible()
  await expect(page.getByRole('spinbutton', { name: '回看周期' })).toBeVisible()
  await expect(page.getByRole('textbox', { name: '阈值' })).toBeVisible()
  await expect(page.getByRole('checkbox', { name: '仅做多' })).toBeVisible()
  await expect(page.getByRole('combobox', { name: '回测合约' })).toBeVisible()

  await expect(page.getByTestId('recent-runs')).toContainText('期货回测链路示例')
  await expect(page.getByTestId('backtest-run-detail')).toContainText('已成功')
  await expect(page.getByTestId('backtest-summary')).toContainText('12.50%')
  await expect(page.getByTestId('backtest-summary')).toContainText('1.82')
  await expect(page.getByTestId('requested-config')).toContainText('future_cash')
  await expect(page.getByTestId('requested-config')).toContainText('1000000')
  await expect(page.getByTestId('effective-config')).toContainText('auto_update_bundle')
  await expect(page.getByTestId('stdout-tail')).toContainText('runner completed safely')
  await expect(page.getByTestId('stderr-tail')).toContainText('research warning only')
  await expect(page.getByTestId('equity-image')).toHaveAttribute('src', `${API_BASE}/runs/${RUN_ID}/artifacts/equity_png`)
  await expect(page.getByTestId('artifact-download-report_zip')).toBeVisible()
  await expect(page.getByTestId('artifact-download-result_pickle')).toBeVisible()

  const downloadPromise = page.waitForEvent('download')
  await page.getByTestId('artifact-download-report_zip').click()
  const download = await downloadPromise
  expect(download.suggestedFilename()).toBe(`${RUN_ID}-report.zip`)
  await expect.poll(() => page.evaluate(() => window.__revokedBacktestBlobUrls.length)).toBe(1)

  expect(store.requests).toContain('GET /api/v1/backtests/health')
  expect(store.requests).toContain('GET /api/v1/backtests/strategies')
  expect(store.requests).toContain('GET /api/v1/backtests/runs?limit=20')
  expect(store.requests).toContain(`GET /api/v1/backtests/runs/${RUN_ID}`)
  expect(store.requests).toContain(`GET /api/v1/backtests/runs/${RUN_ID}/artifacts/report_zip`)
})

test('local ready form submits only declared values and polls running to terminal after two seconds', async ({ page }) => {
  const store = await mockBacktestApi(page, {
    detailResponses: [runDetail('running'), runDetail('succeeded')],
  })

  await page.goto('/backtests')
  await expect(page.getByTestId('backtest-form')).toBeVisible()
  await page.getByTestId('backtest-start-date').fill('2026-01-01')
  await page.getByTestId('backtest-end-date').fill('2026-01-31')
  await page.getByTestId('start-backtest').click()

  await expect(page.getByTestId('backtest-run-detail')).toContainText('运行中')
  await expect.poll(() => store.detailCalls).toBe(3)
  await expect(page.getByTestId('backtest-run-detail')).toContainText('已成功')
  expect(store.postBodies).toEqual([requestedConfig()])
})

test('a ready launch stays disabled without a second POST until terminal health and run refresh complete', async ({ page }) => {
  const terminal = runSummary('succeeded')
  const store = await mockBacktestApi(page, {
    healthResponses: [readyHealth(), readyHealth()],
    runResponses: [[], [terminal]],
    detailResponses: [runDetail('running'), runDetail('succeeded'), runDetail('succeeded')],
  })

  await page.goto('/backtests')
  await page.getByTestId('backtest-start-date').fill('2026-01-01')
  await page.getByTestId('backtest-end-date').fill('2026-01-31')
  const startButton = page.getByRole('button', { name: '启动研究回测' })
  await startButton.click()

  await expect(page.getByTestId('backtest-run-detail')).toContainText('运行中')
  await expect(startButton).toBeDisabled()
  await startButton.click({ force: true })
  expect(store.postBodies).toHaveLength(1)

  await expect.poll(() => store.healthCalls).toBe(2)
  await expect.poll(() => store.runCalls).toBe(2)
  await expect.poll(() => store.detailCalls).toBe(3)
  await expect(page.getByTestId('backtest-run-detail')).toContainText('已成功')
  await expect(startButton).toBeEnabled()
  expect(store.postBodies).toEqual([requestedConfig()])
})

test('an initial busy run refreshes ready capability and restores launch only after terminal', async ({ page }) => {
  const store = await mockBacktestApi(page, {
    healthResponses: [
      readyHealth({ status: 'degraded', busy: true }),
      readyHealth(),
    ],
    runResponses: [
      [runSummary('running')],
      [runSummary('succeeded')],
    ],
    detailResponses: [runDetail('running'), runDetail('succeeded'), runDetail('succeeded')],
  })

  await page.goto('/backtests')

  const startButton = page.getByRole('button', { name: '启动研究回测' })
  await expect(page.getByTestId('backtest-busy')).toContainText('已有任务运行中')
  await expect(startButton).toBeDisabled()
  await expect(page.getByTestId('backtest-run-detail')).toContainText('运行中')

  await expect.poll(() => store.healthCalls).toBe(2)
  await expect.poll(() => store.runCalls).toBe(2)
  await expect.poll(() => store.detailCalls).toBe(3)
  await expect(page.getByTestId('backtest-busy')).toHaveCount(0)
  await expect(page.getByTestId('backtest-run-detail')).toContainText('已成功')
  await expect(startButton).toBeEnabled()
})

test('a failed terminal health probe keeps launch closed while retaining completed detail and retry guidance', async ({ page }) => {
  const store = await mockBacktestApi(page, {
    healthResponses: [readyHealth(), new Error('secret local service failure')],
    runResponses: [[]],
    detailResponses: [runDetail('running'), runDetail('succeeded')],
  })

  await page.goto('/backtests')
  await page.getByTestId('backtest-start-date').fill('2026-01-01')
  await page.getByTestId('backtest-end-date').fill('2026-01-31')
  const startButton = page.getByRole('button', { name: '启动研究回测' })
  await startButton.click()

  await expect(page.getByTestId('backtest-run-detail')).toContainText('运行中')
  await expect.poll(() => store.healthCalls).toBe(2)
  await expect(page.getByTestId('backtest-unavailable')).toContainText('本机回测服务不可用')
  await expect(page.getByTestId('retry-backtest-capability')).toBeVisible()
  await expect(page.getByTestId('backtest-run-detail')).toContainText('已成功')
  await expect(startButton).toBeDisabled()
  await startButton.click({ force: true })

  expect(store.postBodies).toHaveLength(1)
  expect(store.runCalls).toBe(1)
  expect(store.detailCalls).toBe(2)
  await expect(page.getByTestId('backtests-page')).not.toContainText('secret local service failure')
})

test('a deferred terminal refresh cannot overwrite a newer run and unmount clears its poll timer', async ({ page }) => {
  const delayedRuns = deferredResponse()
  const firstRunning = runSummary('running', { strategy_name: '第一个回测' })
  const firstTerminal = runSummary('succeeded', { strategy_name: '第一个回测' })
  const secondRunning = runSummary('running', {
    run_id: SECOND_RUN_ID,
    strategy_name: '第二个回测',
    started_at: '2026-08-23T01:00:01Z',
  })
  const store = await mockBacktestApi(page, {
    healthResponses: [
      readyHealth(),
      readyHealth({ status: 'degraded', busy: true }),
    ],
    runResponses: [
      [firstRunning, secondRunning],
      () => delayedRuns.promise,
    ],
    detailResponses: [
      runDetail('running', { strategy_name: '第一个回测' }),
      runDetail('succeeded', { strategy_name: '第一个回测' }),
      runDetail('succeeded', { strategy_name: '第一个回测' }),
    ],
    detailResponsesByRunId: {
      [SECOND_RUN_ID]: [runDetail('running', {
        run_id: SECOND_RUN_ID,
        strategy_name: '第二个回测',
        started_at: '2026-08-23T01:00:01Z',
      })],
    },
  })

  await page.goto('/backtests')
  await expect(page.getByTestId('backtest-run-detail')).toContainText('运行中')
  await expect.poll(() => store.healthCalls).toBe(2)
  await expect.poll(() => store.runCalls).toBe(2)
  await expect.poll(() => store.detailCallsByRunId[RUN_ID]).toBe(3)

  await page.getByRole('button', { name: /第二个回测/ }).click()
  await expect(page.getByTestId('backtest-run-detail')).toContainText(SECOND_RUN_ID)
  await expect(page.getByTestId('backtest-run-detail')).toContainText('运行中')
  await expect.poll(() => store.detailCallsByRunId[SECOND_RUN_ID]).toBe(1)

  delayedRuns.resolve([firstTerminal, secondRunning])
  await expect.poll(() => store.completedRunCalls).toBe(2)
  await expect(page.getByTestId('backtest-run-detail')).toContainText(SECOND_RUN_ID)
  await expect(page.getByTestId('backtest-run-detail')).not.toContainText(RUN_ID)
  await expect(page.getByTestId('backtest-busy')).toHaveCount(0)

  const secondRunCalls = store.detailCallsByRunId[SECOND_RUN_ID]
  await page.goto('/route-used-to-unmount-backtests')
  await page.waitForTimeout(2200)
  expect(store.detailCallsByRunId[SECOND_RUN_ID]).toBe(secondRunCalls)
})

test('degraded busy health remains observable, blocks submit, and polls the running run to terminal', async ({ page }) => {
  const store = await mockBacktestApi(page, {
    healthResponses: [readyHealth({ status: 'degraded', busy: true })],
    runs: [runSummary('running')],
    detailResponses: [runDetail('running'), runDetail('succeeded')],
  })

  await page.goto('/backtests')

  await expect(page.getByTestId('backtest-form')).toBeVisible()
  await expect(page.getByTestId('backtest-busy')).toContainText('已有任务运行中')
  await expect(page.getByRole('button', { name: '启动研究回测' })).toBeDisabled()
  await expect(page.getByTestId('backtest-run-detail')).toContainText('运行中')
  await expect.poll(() => store.detailCalls).toBe(3)
  await expect(page.getByTestId('backtest-run-detail')).toContainText('已成功')
  expect(store.postBodies).toEqual([])
})

test('terminal failure without result shows duration, failure fields, fixed logs, and safe 404 error', async ({ page }) => {
  await mockBacktestApi(page, {
    runs: [runSummary('failed', { exit_code: 2, failure_code: 'RUNNER_EXITED' })],
    detailResponses: [runDetail('failed', { exit_code: 2, failure_code: 'RUNNER_EXITED' })],
    artifactErrors: { stderr_log: 'BACKTEST_ARTIFACT_NOT_FOUND' },
  })

  await page.goto('/backtests')

  const detail = page.getByTestId('backtest-run-detail')
  await expect(detail).toContainText('耗时')
  await expect(detail).toContainText('7 秒')
  await expect(detail).toContainText('RUNNER_EXITED')
  await expect(detail).toContainText('退出码')
  await expect(detail).toContainText('2')
  await expect(page.getByTestId('artifact-download-stdout_log')).toBeVisible()
  await expect(page.getByTestId('artifact-download-stderr_log')).toBeVisible()
  await expect(page.getByTestId('artifact-download-report_zip')).toHaveCount(0)
  await expect(page.getByTestId('artifact-download-result_pickle')).toHaveCount(0)
  await expect(page.getByTestId('artifact-download-equity_png')).toHaveCount(0)

  await page.getByTestId('artifact-download-stderr_log').click()
  await expect(page.getByTestId('backtest-page-error')).toContainText('该回测产物不可用。')
  await expect(page.getByTestId('backtest-page-error')).not.toContainText('本机回测服务不可用')
})

test('local unavailable retains navigation and gives configuration, start, and retry guidance', async ({ page }) => {
  const store = await mockBacktestApi(page, {
    healthResponses: [new Error('offline'), readyHealth()],
  })

  await page.goto('/backtests')

  await expect(page.getByRole('menuitem', { name: 'RQAlpha 回测' })).toBeVisible()
  await expect(page.getByTestId('backtest-unavailable')).toContainText('仅本机可用')
  await expect(page.getByTestId('backtest-unavailable')).toContainText('VITE_BACKTEST_API_BASE_URL')
  await expect(page.getByTestId('backtest-unavailable')).toContainText('python -m app.backtest.local_app')
  await expect(page.getByTestId('backtest-form')).toHaveCount(0)

  await page.getByTestId('retry-backtest-capability').click()
  await expect(page.getByTestId('backtest-form')).toBeVisible()
  expect(store.healthCalls).toBe(2)
})

test('non-loopback host hides navigation and direct route fails closed with zero sidecar requests', async ({ page }, testInfo) => {
  const localOrigin = new URL(testInfo.project.use.baseURL).origin
  const remoteOrigin = localOrigin.replace('127.0.0.1', '192.0.2.10')
  const loopbackRequests = []

  await page.route(`${API_BASE}/**`, async (route) => {
    loopbackRequests.push(route.request().url())
    await route.abort()
  })
  await page.route(`${remoteOrigin}/**`, async (route) => {
    const requestUrl = new URL(route.request().url())
    const mappedUrl = `${localOrigin}${requestUrl.pathname}${requestUrl.search}`
    const response = await route.fetch({ url: mappedUrl })
    await route.fulfill({ response })
  })

  await page.goto(`${remoteOrigin}/backtests`)

  await expect(page.getByRole('menuitem', { name: 'RQAlpha 回测' })).toHaveCount(0)
  await expect(page.getByTestId('backtest-remote-blocked')).toContainText('仅本机可用')
  await expect(page.getByTestId('backtest-form')).toHaveCount(0)
  await expect(page.getByTestId('start-backtest')).toHaveCount(0)
  await page.waitForTimeout(2200)
  expect(loopbackRequests).toEqual([])
})

test('leaving a running backtest page disposes the pending poll timer', async ({ page }) => {
  const store = await mockBacktestApi(page, {
    runs: [runSummary('running')],
    detailResponses: [runDetail('running')],
  })

  await page.goto('/backtests')
  await expect(page.getByTestId('backtest-run-detail')).toContainText('运行中')
  await expect.poll(() => store.detailCalls).toBe(1)
  await page.goto('/route-used-to-unmount-backtests')
  await page.waitForTimeout(2200)

  expect(store.detailCalls).toBe(1)
})
