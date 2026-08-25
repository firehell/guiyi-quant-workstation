import { expect, test } from '@playwright/test'


function bars(frequency) {
  if (frequency === '1d' || frequency === '1w') {
    const dayStep = frequency === '1d' ? 1 : 7
    return Array.from({ length: 32 }, (_, index) => {
      const barEnd = new Date(Date.UTC(2026, 0, 1 + index * dayStep)).toISOString()
      return {
        bar_end: barEnd,
        trading_day: barEnd.slice(0, 10),
        open: 100,
        high: 101,
        low: 99,
        close: 100,
        volume: 10,
        turnover: null,
        open_interest: null,
      }
    })
  }
  const step = Number.parseInt(frequency, 10)
  return Array.from({ length: 32 }, (_, index) => {
    const barEnd = new Date(Date.UTC(2026, 7, 13, 0, index * step)).toISOString()
    return {
      bar_end: barEnd,
      trading_day: '2026-08-13',
      open: 100,
      high: 101,
      low: 99,
      close: 100,
      volume: 10,
      turnover: null,
      open_interest: null,
    }
  })
}

function event({ id, ruleCode, frequency, barEnd, resultCode }) {
  return {
    id,
    rule_code: ruleCode,
    symbol: 'ag',
    contract: 'AG2610',
    trading_day: barEnd.slice(0, 10),
    frequency,
    bar_end: barEnd,
    result_codes: [resultCode],
    lower_tf_confirmation: false,
    detected_at: '2026-08-13T07:45:01Z',
    notification_attempted_at: '2026-08-13T07:45:01Z',
  }
}

test('persistent Alert V2 markers stay exact-frequency and actual-dominant only', async ({ page }) => {
  await page.setViewportSize({ width: 1680, height: 1000 })
  await page.addInitScript(() => {
    window.__GUIYI_E2E_CANVAS_TEXT__ = []
    const original = CanvasRenderingContext2D.prototype.fillText
    CanvasRenderingContext2D.prototype.fillText = function (value, ...args) {
      window.__GUIYI_E2E_CANVAS_TEXT__.push(String(value))
      return original.call(this, value, ...args)
    }
  })
  const requests = []
  let activeFrequency = '30m'
  const frequencies = ['1m', '5m', '15m', '30m', '60m', '1d', '1w']
  const barsByFrequency = Object.fromEntries(frequencies.map((frequency) => [frequency, bars(frequency)]))
  const requestedRuleCodesFor = (frequency) => [...new Set(
    requests
      .filter((request) => request.activeFrequency === frequency)
      .map((request) => request.ruleCode),
  )].sort()

  await page.route('**/api/v1/market/**', async (route) => {
    const url = new URL(route.request().url())
    if (url.pathname.endsWith('/dominants')) return route.fulfill({ json: { items: [
      { product: 'ag', product_name: '白银', sector: 'precious', exchange: 'SHFE', actual_contract: 'AG2610', dominant_mapping_date: '2026-08-13' },
    ] } })
    if (url.pathname.endsWith('/bars/page')) {
      activeFrequency = url.searchParams.get('frequency')
      const seriesKind = url.searchParams.get('series_kind')
      const marketBars = barsByFrequency[activeFrequency]
      return route.fulfill({ json: {
        request: {
          series_kind: seriesKind,
          symbol: 'ag',
          contract: url.searchParams.get('contract'),
          frequency: activeFrequency,
          before: null,
          limit: 1200,
        },
        bars: marketBars,
        canonical_coverage: null,
        page: { has_more_before: false, next_before: null },
        resolved_contract_segments: seriesKind === 'actual_dominant'
          ? [{
              contract: 'AG2610',
              start_trading_day: marketBars[0].trading_day,
              end_trading_day: marketBars.at(-1).trading_day,
            }]
          : [],
      } })
    }
    if (url.pathname.endsWith('/state')) return route.fulfill({ json: {
      symbol: 'ag', series_kind: url.searchParams.get('series_kind'), frequency: activeFrequency, operational: true,
      phase: 'CLOSED', trading_day: barsByFrequency[activeFrequency].at(-1).trading_day, live_eligible: false, live_available: false,
      live_contract: null, canonical_end: barsByFrequency[activeFrequency]?.at(-1)?.bar_end ?? null, after_market: {},
    } })
    if (url.pathname.endsWith('/research/product')) return route.fulfill({ status: 409, json: { detail: { code: 'QUERY_WINDOW_EMPTY' } } })
    if (url.pathname.endsWith('/research/main-force-mirror')) return route.fulfill({ status: 400, json: { detail: { code: 'MFM_V2_UNSUPPORTED_FREQUENCY' } } })
    return route.abort()
  })
  await page.route('**/api/runtime/health', (route) => route.fulfill({ json: {
    status: 'ok', components: { alert: { status: 'disabled' } },
  } }))
  await page.route('**/api/alerts/**', async (route) => {
    const url = new URL(route.request().url())
    if (url.pathname.endsWith('/products/ag')) return route.fulfill({ json: { symbol: 'ag', rules: [
      { rule_code: 'htdy_original_15m', display_name: '火天大有', kind: 'indicator_observation', input_frequencies: frequencies, enabled_for_product: false, enabled_frequencies: [] },
      { rule_code: 'subing_entry_signal_v1', display_name: '苏冰入场信号', kind: 'formal_signal', input_frequencies: ['5m', '15m'], enabled_for_product: false, enabled_frequencies: [] },
    ] } })
    if (url.pathname.endsWith('/current-events')) return route.fulfill({ json: { status: 'ready', trading_day: '2026-08-13', items: [] } })
    if (url.pathname.endsWith('/events')) {
      const ruleCode = url.searchParams.get('rule_code')
      requests.push({ ruleCode, activeFrequency })
      const items = ruleCode === 'htdy_original_15m'
        ? [event({
            id: frequencies.indexOf(activeFrequency) + 10,
            ruleCode,
            frequency: activeFrequency,
            barEnd: barsByFrequency[activeFrequency].at(-1).bar_end,
            resultCode: 'sell',
          })]
        : [
            event({ id: 1, ruleCode, frequency: '5m', barEnd: barsByFrequency['5m'].at(-1).bar_end, resultCode: 'buy' }),
            event({ id: 2, ruleCode, frequency: '15m', barEnd: barsByFrequency['15m'].at(-1).bar_end, resultCode: 'buy' }),
          ]
      return route.fulfill({ json: { items } })
    }
    return route.abort()
  })

  await page.goto('/market/chart?symbol=ag&series_kind=actual_dominant&frequency=30m')
  const sidebar = page.locator('.product-workspace__sidebar')
  await expect(sidebar).toBeVisible()
  await expect(sidebar.getByTestId('product-check-now')).toBeVisible()
  await expect(sidebar.getByTestId('subing-panel')).toHaveCount(1)
  await expect(sidebar.getByTestId('product-alert-rules')).toHaveCount(0)
  await expect(sidebar.getByTestId('product-check-more')).not.toHaveAttribute('open')
  expect(await sidebar.locator('[data-testid="product-check-now"], [data-testid="product-check-observation"], [data-testid="product-check-more"]').evaluateAll((nodes) => (
    nodes.every((node, index) => index === 0 || Boolean(nodes[index - 1].compareDocumentPosition(node) & Node.DOCUMENT_POSITION_FOLLOWING))
  ))).toBe(true)
  await sidebar.getByTestId('product-check-more').locator('summary').click()
  await expect(sidebar.getByTestId('product-today-alert-events')).toBeVisible()
  await page.getByRole('group', { name: 'Overlay' }).getByRole('button', { name: '火天大有', exact: true }).click()
  await expect(sidebar.getByTestId('subing-panel')).toHaveCount(0)
  await expect(sidebar.getByTestId('product-alert-rules')).toBeVisible()
  await page.getByRole('button', { name: '真实主力', exact: true }).click()
  await expect(page.getByTestId('htdy-chart-legend')).toBeVisible()
  await expect(page.getByText('当前序列或周期不支持该 Overlay')).toHaveCount(0)

  await page.getByRole('button', { name: '1m', exact: true }).click()
  await expect(page.getByTestId('htdy-chart-legend')).toBeVisible()
  await expect(page.getByTestId('kline-shell')).toHaveAttribute('data-alert-marker-count', '1')
  await expect.poll(() => requestedRuleCodesFor('1m'))
    .toEqual(['htdy_original_15m'])

  await page.getByRole('button', { name: '5m', exact: true }).click()
  await expect.poll(() => requestedRuleCodesFor('5m'))
    .toEqual(['htdy_original_15m', 'subing_entry_signal_v1'])
  await expect(page.getByTestId('kline-shell')).toHaveAttribute('data-alert-marker-count', '2')

  await page.getByRole('button', { name: '15m', exact: true }).click()
  await expect(page.getByTestId('kline-shell')).toHaveAttribute('data-alert-marker-count', '2')
  await expect.poll(() => page.evaluate(() => window.__GUIYI_E2E_CANVAS_TEXT__)).toEqual(
    expect.arrayContaining(['卖出观察', '买入信号']),
  )
  await expect.poll(() => requestedRuleCodesFor('15m'))
    .toEqual(['htdy_original_15m', 'subing_entry_signal_v1'])

  for (const frequency of ['30m', '60m']) {
    await page.getByRole('button', { name: frequency, exact: true }).click()
    await expect(page.getByTestId('htdy-chart-legend')).toBeVisible()
    await expect(page.getByTestId('kline-shell')).toHaveAttribute('data-alert-marker-count', '1')
    await expect.poll(() => requestedRuleCodesFor(frequency))
      .toEqual(['htdy_original_15m'])
  }

  for (const [frequency, buttonName] of [['1d', 'D'], ['1w', 'W']]) {
    await page.getByRole('button', { name: buttonName, exact: true }).click()
    await expect(page.getByTestId('market-display-state')).toHaveText('Historical')
    await expect(page.getByTestId('htdy-chart-legend')).toBeVisible()
    await expect(page.getByTestId('kline-shell')).toHaveAttribute('data-alert-marker-count', '1')
    await expect.poll(() => requestedRuleCodesFor(frequency))
      .toEqual(['htdy_original_15m'])
  }

  await page.getByRole('button', { name: '15m', exact: true }).click()

  const tabs = page.getByTestId('secondary-panel-tabs')
  await expect(tabs.getByRole('tab')).toHaveText(['MACD', '主力照妖镜 V2'])
  await page.evaluate(() => { window.__GUIYI_E2E_CANVAS_TEXT__ = [] })
  await tabs.getByRole('tab', { name: 'MACD' }).click()
  await expect(page.getByTestId('kline-shell')).toHaveAttribute('data-alert-marker-count', '2')
  await expect.poll(() => page.evaluate(() => window.__GUIYI_E2E_CANVAS_TEXT__)).toEqual(
    expect.arrayContaining(['卖出观察', '买入信号']),
  )

  const eventRequestCount = requests.length
  await page.getByRole('button', { name: '主连', exact: true }).click()
  await expect(page.getByTestId('htdy-chart-legend')).toBeVisible()
  await expect(page.getByTestId('kline-shell')).toHaveAttribute('data-alert-marker-count', '0')
  await page.waitForTimeout(100)
  expect(requests).toHaveLength(eventRequestCount)

  await page.getByRole('button', { name: '图表设置', exact: true }).click()
  await page.getByPlaceholder('例如 JM2601').fill('AG2610')
  await page.getByRole('button', { name: '使用指定合约', exact: true }).click()
  await expect(page.getByTestId('htdy-chart-legend')).toBeVisible()
  await expect(page.getByTestId('kline-shell')).toHaveAttribute('data-alert-marker-count', '0')
  await page.waitForTimeout(100)
  expect(requests).toHaveLength(eventRequestCount)
})

test('SuBing product and HTDY pair switches preserve separate Scope semantics', async ({ page }) => {
  await page.setViewportSize({ width: 1680, height: 1000 })
  const frequencies = ['1m', '5m', '15m', '30m', '60m', '1d', '1w']
  const barsByFrequency = {
    '5m': bars('5m'),
    '15m': bars('15m'),
  }
  const enabledFrequencies = new Set(['15m'])
  let subingEnabled = false
  const scopePuts = []

  await page.route('**/api/v1/market/**', async (route) => {
    const url = new URL(route.request().url())
    if (url.pathname.endsWith('/dominants')) return route.fulfill({ json: { items: [
      { product: 'jm', product_name: '焦煤', sector: 'black', exchange: 'DCE', actual_contract: 'JM2609', dominant_mapping_date: '2026-08-13' },
    ] } })
    if (url.pathname.endsWith('/bars/page')) {
      const frequency = url.searchParams.get('frequency')
      const marketBars = barsByFrequency[frequency]
      return route.fulfill({ json: {
        request: {
          series_kind: 'actual_dominant',
          symbol: 'jm',
          contract: null,
          frequency,
          before: null,
          limit: 1200,
        },
        bars: marketBars,
        canonical_coverage: null,
        page: { has_more_before: false, next_before: null },
        resolved_contract_segments: [{
          contract: 'JM2609',
          start_trading_day: marketBars[0].trading_day,
          end_trading_day: marketBars.at(-1).trading_day,
        }],
      } })
    }
    if (url.pathname.endsWith('/state')) {
      const frequency = url.searchParams.get('frequency')
      return route.fulfill({ json: {
        symbol: 'jm',
        series_kind: 'actual_dominant',
        frequency,
        operational: true,
        phase: 'CLOSED',
        trading_day: '2026-08-13',
        live_eligible: false,
        live_available: false,
        live_contract: null,
        canonical_end: barsByFrequency[frequency].at(-1).bar_end,
        after_market: {},
      } })
    }
    if (url.pathname.endsWith('/research/product')) {
      return route.fulfill({ status: 409, json: { detail: { code: 'QUERY_WINDOW_EMPTY' } } })
    }
    if (url.pathname.endsWith('/research/main-force-mirror')) {
      return route.fulfill({ status: 400, json: { detail: { code: 'MFM_V2_UNSUPPORTED_FREQUENCY' } } })
    }
    return route.abort()
  })
  await page.route('**/api/runtime/health', (route) => route.fulfill({ json: {
    status: 'ok', components: { alert: { status: 'disabled' } },
  } }))
  await page.route('**/api/alerts/**', async (route) => {
    const url = new URL(route.request().url())
    if (route.request().method() === 'PUT') {
      const enabled = route.request().postDataJSON().enabled
      scopePuts.push({ path: url.pathname, enabled })
      if (url.pathname.endsWith('/rules/subing_entry_signal_v1/scope/jm')) {
        subingEnabled = enabled
        return route.fulfill({ json: {
          rule_code: 'subing_entry_signal_v1',
          display_name: '苏冰入场信号',
          kind: 'formal_signal',
          input_frequencies: ['5m', '15m'],
          enabled_for_product: subingEnabled,
          enabled_frequencies: [],
        } })
      }
      const frequency = url.pathname.split('/').at(-1)
      if (enabled) enabledFrequencies.add(frequency)
      else enabledFrequencies.delete(frequency)
      return route.fulfill({ json: {
        rule_code: 'htdy_original_15m',
        display_name: '火天大有',
        kind: 'indicator_observation',
        input_frequencies: frequencies,
        enabled_for_product: enabledFrequencies.size > 0,
        enabled_frequencies: [...enabledFrequencies],
      } })
    }
    if (url.pathname.endsWith('/products/jm')) return route.fulfill({ json: { symbol: 'jm', rules: [
      {
        rule_code: 'htdy_original_15m',
        display_name: '火天大有',
        kind: 'indicator_observation',
        input_frequencies: frequencies,
        enabled_for_product: true,
        enabled_frequencies: [...enabledFrequencies],
      },
      {
        rule_code: 'subing_entry_signal_v1',
        display_name: '苏冰入场信号',
        kind: 'formal_signal',
        input_frequencies: ['5m', '15m'],
        enabled_for_product: false,
        enabled_frequencies: [],
      },
    ] } })
    if (url.pathname.endsWith('/current-events')) {
      return route.fulfill({ json: { status: 'ready', trading_day: '2026-08-13', items: [] } })
    }
    if (url.pathname.endsWith('/events')) return route.fulfill({ json: { items: [] } })
    return route.abort()
  })

  await page.goto('/market/chart?symbol=jm&series_kind=actual_dominant&frequency=15m')
  const sidebar = page.locator('.product-workspace__sidebar')
  const htdyRow = sidebar.locator('.product-alert-rules__row').filter({ hasText: '火天大有' })
  const htdySwitch = htdyRow.getByRole('switch')
  const periods = page.getByRole('group', { name: '周期' })
  const overlays = page.getByRole('group', { name: 'Overlay' })

  const subingScope = sidebar.getByTestId('subing-alert-scope')
  const subingSwitch = subingScope.getByRole('switch')
  await expect(subingSwitch).not.toBeChecked()
  expect(scopePuts).toEqual([])
  await subingSwitch.click()
  await expect(subingSwitch).toBeChecked()
  expect(scopePuts).toEqual([
    { path: '/api/alerts/rules/subing_entry_signal_v1/scope/jm', enabled: true },
  ])

  const putCountBeforeJdj = scopePuts.length
  await overlays.getByRole('button', { name: '日进斗金策略', exact: true }).click()
  await expect(sidebar).toContainText('Reference only')
  await expect(sidebar.getByRole('switch')).toHaveCount(0)
  expect(scopePuts).toHaveLength(putCountBeforeJdj)
  await overlays.getByRole('button', { name: '火天大有', exact: true }).click()

  await expect(htdyRow).toContainText('火天大有 · 15m')
  await expect(htdySwitch).toBeChecked()
  expect(scopePuts).toHaveLength(1)

  await periods.getByRole('button', { name: '5m', exact: true }).click()
  await expect(htdyRow).toContainText('火天大有 · 5m')
  await expect(htdySwitch).not.toBeChecked()
  expect(scopePuts).toHaveLength(1)

  await htdySwitch.click()
  await expect(htdySwitch).toBeChecked()
  expect(scopePuts.filter((item) => item.path.includes('htdy_original_15m'))).toEqual([
    { path: '/api/alerts/rules/htdy_original_15m/scope/jm/5m', enabled: true },
  ])

  await periods.getByRole('button', { name: '15m', exact: true }).click()
  await expect(htdyRow).toContainText('火天大有 · 15m')
  await expect(htdySwitch).toBeChecked()
  expect(scopePuts.filter((item) => item.path.includes('htdy_original_15m'))).toHaveLength(1)

  await periods.getByRole('button', { name: '5m', exact: true }).click()
  await expect(htdySwitch).toBeChecked()
  await htdySwitch.click()
  await expect(htdySwitch).not.toBeChecked()
  expect(scopePuts.filter((item) => item.path.includes('htdy_original_15m'))).toEqual([
    { path: '/api/alerts/rules/htdy_original_15m/scope/jm/5m', enabled: true },
    { path: '/api/alerts/rules/htdy_original_15m/scope/jm/5m', enabled: false },
  ])

  await periods.getByRole('button', { name: '15m', exact: true }).click()
  await expect(htdySwitch).toBeChecked()
  const putCountBeforeOverlay = scopePuts.length
  await overlays.getByRole('button', { name: '火天大有', exact: true }).click()
  await overlays.getByRole('button', { name: '无', exact: true }).click()
  expect(scopePuts).toHaveLength(putCountBeforeOverlay)
})
