import { expect, test } from '@playwright/test'

const config = {
  strategy_id: 'newow_trend', product: 'FU', contract: 'FU2603', signal_frequency: '5m',
  formula_version: 'trend-v1', profile_id: 'profile-v1', warmup_start: '2026-01-05',
  start: '2026-02-02', end: '2026-02-03', initial_capital: '100000',
}
const run = (run_id, status = 'SUCCEEDED') => ({
  config, run_id, status, created_at: '2026-11-28T11:00:00+08:00',
  updated_at: '2026-11-28T11:01:00+08:00', phase: 'PUBLISHED', qualification: 'TRIAL',
  summary: { metrics: { net_return: { value: '0.012', definition: '扣费后的结算权益变化' } } },
})
const trade = {
  trade_id: 'trade-A', contract: 'FU2603', direction: 'LONG', quantity: 1,
  entry_at: '2026-02-02T09:06:00+08:00', entry_price: '2800', entry_signal_id: 'signal-A',
  status: 'OPEN', unrealized_pnl: '35', fees: '3',
}

test('keeps the open result and its Quant Chart replay bound to the selected Run', async ({ page }) => {
  const requests = []
  let recent = ['A']
  await page.route('**/api/v1/backtests/**', async route => {
    const { pathname, searchParams } = new URL(route.request().url())
    const path = pathname.replace('/api/v1/backtests', '')
    requests.push([route.request().method(), path, searchParams.get('offset')])
    if (path === '/eligibility' || path === '/templates' || path === '/experiments') return route.fulfill({ json: { items: [] } })
    if (path === '/runs') return route.fulfill({ json: {
      items: recent.map(id => run(id)), total: recent.length, counts: { SUCCEEDED: recent.length },
      latest_attempt: run(recent[0]), latest_success: run(recent[0]),
    } })
    if (path === '/runs/A/events') return route.fulfill({ json: { run_id: 'A', items: [] } })
    if (path === '/runs/A') return route.fulfill({ json: run('A') })
    if (path === '/runs/A/trades') return route.fulfill({ json: {
      run_id: 'A', total: 51,
      items: [searchParams.get('offset') === '50' ? trade : { ...trade, trade_id: 'trade-first', unrealized_pnl: '29' }],
    } })
    if (path === '/runs/A/replay/trade-A') return route.fulfill({ json: {
      available: true, run_id: 'A', contract: 'FU2603', frequency: '5m', revision: 'plus-frozen-A',
      trade, bars: [
        { at: '2026-02-02T09:05:00+08:00', open: '2808', high: '2810', low: '2800', close: '2803' },
        { at: '2026-02-02T09:10:00+08:00', open: '2803', high: '2807', low: '2798', close: '2805' },
      ],
      markers: [{ at: '2026-02-02T09:10:00+08:00', kind: 'ENTRY', price: '2800', trade_id: 'trade-A' }],
      native_fills: [{
        native_trade_id: 'native-A', signal_id: 'signal-A', position_effect: 'OPEN', price: '2800', fee: '3',
        native_order_at: '2026-02-02T09:06:00+08:00', modeled_fill_at: '2026-02-02T09:06:00+08:00',
        native_fill_at: '2026-02-02T09:07:00+08:00',
      }],
      attempts: [{
        signal_id: 'signal-A', signal_bar_end: '2026-02-02T09:05:00+08:00', signal_available_at: '2026-02-02T09:05:02+08:00',
      }],
    } })
    return route.fulfill({ status: 404, json: {detail: {code: 'NOT_FOUND'}} })
  })

  await page.goto('/backtests')
  const workbench = page.getByRole('main')
  await expect(workbench.getByRole('heading', { name: '回测中心', exact: true })).toBeVisible()
  await workbench.getByRole('link', { name: 'A', exact: true }).first().click()
  await page.getByRole('button', { name: '交易明细' }).click()
  await expect(page.getByRole('button', { name: 'trade-first' })).toBeVisible()
  recent = ['B', 'A']
  await page.getByRole('button', { name: '下一页' }).click()
  await page.getByRole('button', { name: 'trade-A' }).click()
  await expect(page.getByRole('img', { name: '同 Run 的成交回放' })).toBeVisible()
  await expect(page.locator('.backtest-chart canvas').first()).toBeVisible()
  await expect(page.getByText('plus-frozen-A', { exact: true })).toBeVisible()
  await expect(page.getByText('未实现盈亏', { exact: true }).last()).toBeVisible()
  const clocks = page.getByRole('table', { name: '成交时钟与对账' })
  await expect(clocks.getByText('2026-02-02T09:05:02+08:00', { exact: true })).toBeVisible()
  await expect(clocks.getByText('2026-02-02T09:06:00+08:00', { exact: true })).toHaveCount(2)
  await expect(clocks.getByText('2026-02-02T09:07:00+08:00', { exact: true })).toBeVisible()
  expect(requests.some(([, path, offset]) => path === '/runs/A/trades' && offset === '50')).toBe(true)
  expect(requests.every(([method]) => method === 'GET')).toBe(true)
  expect(requests.some(([, path]) => path.startsWith('/runs/B'))).toBe(false)
})

test('diagnoses six strategies and submits a frozen historical configuration through the native entry', async ({ page }) => {
  const entries = [
    ['newow_trend', '牛哇趋势', 'TRIAL', 'FU 已核验试验'],
    ['newow_oscillation', '牛哇震荡', 'UNVERIFIED', '同 Bar 执行待核验'],
    ['newow_main_rise', '牛哇主升浪', 'UNVERIFIED', '减仓政策待核验'],
    ['newow_dual_fusion', '牛哇双策略', 'UNVERIFIED', '合成政策待核验'],
    ['htdy_60m', '火天大有 60m', 'BLOCKED', '回看重绘'],
    ['subing_portfolio_16', '苏冰共享 Paper', 'DOMAIN_OWNED', '沿用独立回放'],
  ]
  let firstRequest
  let submitted
  await page.route('**/api/v1/backtests/**', async route => {
    const path = new URL(route.request().url()).pathname.replace('/api/v1/backtests', '')
    if (path === '/eligibility') return route.fulfill({ json: { items: entries.map(([strategy_id, label, status, reason]) => ({
      strategy_id, label, status, reason, ...(strategy_id === 'newow_trend' ? {
        product: 'FU', signal_frequency: '5m', execution_frequency: '1m', formula_version: 'trend-v1', profile_id: 'profile-v1',
        research_parameters: { execution_delay_minutes: { min: 0, max: 3, default: 0 } },
      } : {}),
    })) } })
    if (path === '/templates') return route.fulfill({ json: { items: [] } })
    if (path === '/runs' && route.request().method() === 'POST') {
      if (!firstRequest) {
        firstRequest = route.request().postDataJSON()
        return route.abort('failed')
      }
      submitted = route.request().postDataJSON()
      return route.fulfill({ status: 202, json: run('new-run', 'QUEUED') })
    }
    if (path === '/runs') return route.fulfill({ json: { items: [], total: 0, counts: {} } })
    if (path === '/runs/new-run/events') return route.fulfill({ json: { run_id: 'new-run', items: [] } })
    if (path === '/runs/new-run') return route.fulfill({ json: run('new-run', 'QUEUED') })
    return route.fulfill({ status: 404, json: {detail: {code: 'NOT_FOUND'}} })
  })

  await page.goto('/backtests?view=config&strategy=newow_trend')
  await expect(page.getByLabel('回测接入资格').getByRole('row')).toHaveCount(7)
  await expect(page.getByText('回看重绘', { exact: true })).toBeVisible()
  async function fillConfig() {
    await page.getByLabel('物理合约').fill('FU2603')
    await page.getByLabel('预热开始').fill('2026-01-05')
    await page.getByLabel('评价开始').fill('2026-02-02')
    await page.getByLabel('评价结束').fill('2026-02-03')
  }
  await fillConfig()
  const delay = page.getByLabel('执行延迟（分钟）')
  await expect(delay).toHaveValue('0')
  await expect(delay.getByRole('option')).toHaveText(['0', '1', '2', '3'])
  await delay.selectOption('3')
  await page.getByRole('button', { name: '提交回测' }).click()
  await expect(page.getByRole('alert')).toContainText('提交结果未确认')
  await page.reload()
  await fillConfig()
  await delay.selectOption('3')
  await page.getByRole('button', { name: '提交回测' }).click()
  await expect(page).toHaveURL(/\/backtests\/new-run/)
  expect(submitted).toEqual(firstRequest)
  expect(submitted.config).toMatchObject({ ...config, parameters: { execution_delay_minutes: 3 } })
})

test('submits fixed OOS windows and reads the selected fold and member Run', async ({ page }) => {
  const fold = {
    train_warmup_start: '2026-01-05', train_start: '2026-02-02', train_end: '2026-02-03',
    test_warmup_start: '2026-01-06', test_start: '2026-02-04', test_end: '2026-02-05',
  }
  const definition = [
    { template_id: 'base', name: '原始成本', config },
    { template_id: 'delayed', name: '延迟两分钟', config: { ...config, parameters: { execution_delay_minutes: '2' } } },
  ]
  const experiment = { experiment_id: 'oos-test', kind: 'oos', status: 'SUCCEEDED', created_at: '2026-11-28T11:00:00+08:00' }
  let submitted
  await page.route('**/api/v1/backtests/**', async route => {
    const path = new URL(route.request().url()).pathname.replace('/api/v1/backtests', '')
    if (path === '/templates') return route.fulfill({ json: { items: definition } })
    if (path === '/experiments' && route.request().method() === 'POST') {
      submitted = route.request().postDataJSON()
      return route.fulfill({ json: experiment })
    }
    if (path === '/experiments') return route.fulfill({ json: { items: submitted ? [experiment] : [], total: Number(Boolean(submitted)) } })
    if (path === '/experiments/oos-test') return route.fulfill({ json: {
      ...experiment, definition: submitted,
      members: [{
        member_id: 'member-test', run_id: 'oos-run', phase: 'test', fold: 1,
        research_config: { ...config, start: fold.test_start, end: fold.test_end }, status: 'SUCCEEDED',
        metrics: { net_return: '0.029', max_drawdown: '0.004', trade_count: 6 },
      }],
      folds: [{
        fold: 1, selection_cutoff: '2026-02-03T18:00:00+08:00', selected_member_id: 'selected-train', test_member_id: 'member-test',
        status: 'SUCCEEDED', boundary_policy: 'settlement_mark_then_flat_start_v1', test_initial_position: 'FLAT', test_initial_equity: '100000',
      }],
    } })
    if (path === '/experiments/oos-test/evidence') return route.fulfill({ json: {
      ...experiment, metrics: { net_return: '0.029', max_drawdown: '0.004' }, run_ids: ['oos-run'], missing_folds: [],
    } })
    if (path === '/runs/oos-run/events') return route.fulfill({ json: { run_id: 'oos-run', items: [] } })
    if (path === '/runs/oos-run') return route.fulfill({ json: run('oos-run') })
    return route.fulfill({ status: 404, json: {detail: {code: 'NOT_FOUND'}} })
  })

  await page.goto('/backtests?view=validation')
  await page.getByLabel('执行参数', { exact: true }).check()
  await page.getByLabel('原始成本').check()
  await page.getByLabel('延迟两分钟').check()
  await expect(page.getByText(/执行延迟 2 分钟/)).toBeVisible()
  for (const [label, key] of [
    ['训练预热', 'train_warmup_start'], ['训练开始', 'train_start'], ['训练结束', 'train_end'],
    ['测试预热', 'test_warmup_start'], ['测试开始', 'test_start'], ['测试结束', 'test_end'],
  ]) await page.getByLabel(label).fill(fold[key])
  await page.getByRole('button', { name: '冻结定义并提交' }).click()
  await expect(page.getByText('样本外证据 · 成功')).toBeVisible()
  await expect(page.getByText('selected-train', { exact: true })).toBeVisible()
  expect(submitted).toMatchObject({ kind: 'oos', axes: ['parameters'], configs: definition.map(item => item.config), folds: [fold] })
  await page.getByRole('link', { name: 'member-test', exact: true }).click()
  await expect(page).toHaveURL(/\/backtests\/oos-run/)
})

test('compares execution delays using two templates with the same formula', async ({ page }) => {
  const configs = [config, { ...config, parameters: { execution_delay_minutes: '2' } }]
  const experiment = { experiment_id: 'delay-test', kind: 'comparison', status: 'SUCCEEDED', created_at: '2026-11-28T11:00:00+08:00' }
  let submitted
  await page.route('**/api/v1/backtests/**', async route => {
    const path = new URL(route.request().url()).pathname.replace('/api/v1/backtests', '')
    if (path === '/templates') return route.fulfill({ json: {
      items: configs.map((row, index) => ({ template_id: `delay-${index}`, name: index ? '延迟模板' : '基准模板', config: row })),
    } })
    if (path === '/experiments' && route.request().method() === 'POST') {
      submitted = route.request().postDataJSON()
      return route.fulfill({ json: experiment })
    }
    if (path === '/experiments') return route.fulfill({ json: { items: submitted ? [experiment] : [], total: Number(Boolean(submitted)) } })
    if (path === '/experiments/delay-test') return route.fulfill({ json: {
      ...experiment, definition: submitted,
      comparison: { comparable: true, metric: 'net_return', ranked_member_ids: ['delay-1', 'delay-0'] },
      members: configs.map((row, index) => ({
        member_id: `delay-${index}`, run_id: `run-${index}`, phase: 'comparison', research_config: row, status: 'SUCCEEDED',
      })),
    } })
    return route.fulfill({ status: 404, json: { detail: { code: 'NOT_FOUND' } } })
  })
  await page.goto('/backtests?view=experiments')
  await page.getByLabel('执行参数', { exact: true }).check()
  await page.getByLabel('基准模板').check()
  await page.getByLabel('延迟模板').check()
  await page.getByRole('button', { name: '冻结定义并提交' }).click()
  await expect(page.getByText('同口径比较', { exact: true })).toBeVisible()
  await expect(page.getByRole('row').filter({ hasText: 'delay-0' }).getByRole('cell', { name: '0 分钟' })).toBeVisible()
  await expect(page.getByRole('row').filter({ hasText: 'delay-1' }).getByRole('cell', { name: '2 分钟' })).toBeVisible()
  expect(submitted).toMatchObject({ kind: 'comparison', axes: ['parameters'], configs })
  expect(submitted.folds).toBeUndefined()
})

test('shows a failed Plus preflight without a report or admission snapshot', async ({ page }) => {
  await page.route('**/api/v1/backtests/runs/no-rates', route => route.fulfill({ json: {
    ...run('no-rates', 'FAILED'), qualification: 'UNVERIFIED', snapshot: null, phase: 'ENGINE_STOPPED',
    diagnostic: 'PLUS_POINT_IN_TIME_TRADING_PARAMETERS_UNAVAILABLE',
  } }))
  await page.route('**/api/v1/backtests/runs/no-rates/events', route => route.fulfill({ json: { run_id: 'no-rates', items: [] } }))
  await page.goto('/backtests/no-rates')
  await expect(page.getByRole('status')).toHaveText('当前 Plus 本地数据缺少按交易日生效的手续费和保证金依据。')
  await expect(page.getByText('研究资格 未核验')).toBeVisible()
  await expect(page.getByText('提交时冻结的配置请求')).toBeVisible()
  await expect(page.getByText('引擎准入快照')).toHaveCount(0)
  await expect(page.getByRole('button', { name: '报告', exact: true })).toHaveCount(0)
  await expect(page.getByText('净累计收益', { exact: true })).toHaveCount(0)
})

test('keeps each partial fill and the old-contract valuation visible through same-Run pagination', async ({ page }) => {
  const interrupted = {
    ...trade, trade_id: 'rollover-A', status: 'ROLLOVER_INTERRUPTED', quantity: 3,
    native_entry_ids: ['open-1', 'open-2'], native_exit_ids: ['close-1'],
    net_pnl: '12', unrealized_pnl: '35', mark_price: '2807', marked_at: '2026-02-02T15:00:00+08:00',
  }
  const fill = (native_trade_id, position_effect, quantity, minute) => ({
    native_trade_id, native_order_id: 'order-' + native_trade_id, position_effect, quantity, contract: 'FU2603',
    signal_id: 'signal-' + native_trade_id, price: '2801', fee: '3',
    modeled_fill_at: `2026-02-02T09:${minute}:00+08:00`, native_fill_at: `2026-02-02T09:${minute}:30+08:00`,
  })
  const fills = [fill('open-1', 'OPEN', 1, '06'), fill('open-2', 'OPEN', 2, '07'), fill('close-1', 'CLOSE_TODAY', 1, '08')]
  const requests = []
  let newest = 'rollover-run'
  await page.route('**/api/v1/backtests/**', async route => {
    const { pathname, searchParams } = new URL(route.request().url())
    const path = pathname.replace('/api/v1/backtests', '')
    requests.push([route.request().method(), path])
    if (path === '/experiments') return route.fulfill({ json: { items: [] } })
    if (path === '/runs') return route.fulfill({ json: {
      items: [run(newest)], total: 1, counts: { SUCCEEDED: 1 }, latest_attempt: run(newest), latest_success: run(newest),
    } })
    if (path === '/runs/rollover-run') return route.fulfill({ json: run('rollover-run') })
    if (path === '/runs/rollover-run/events') return route.fulfill({ json: { run_id: 'rollover-run', items: [] } })
    if (path === '/runs/rollover-run/trades') return route.fulfill({ json: {
      run_id: 'rollover-run', total: 51,
      items: [searchParams.get('offset') === '50' ? { ...trade, trade_id: 'trade-on-page-2' } : interrupted],
    } })
    if (path === '/runs/rollover-run/replay/rollover-A') return route.fulfill({ json: {
      run_id: 'rollover-run', contract: 'FU2603', frequency: '5m', revision: 'old-month-revision',
      available: false, reason: 'RUN_CHART_WINDOW_UNAVAILABLE', trade: interrupted, bars: [], markers: [],
      native_fills: fills, attempts: [],
    } })
    if (path === '/runs/rollover-run/replay/trade-on-page-2') return route.fulfill({ json: {
      run_id: 'rollover-run', contract: 'FU2603', frequency: '5m', revision: 'old-month-revision',
      available: true, trade: { ...interrupted, trade_id: 'trade-on-page-2' }, native_fills: fills, attempts: [],
      bars: [
        { at: '2026-02-02T09:10:00+08:00', open: '2808', high: '2810', low: '2800', close: '2803', in_position: true },
        { at: '2026-02-02T15:00:00+08:00', open: '2803', high: '2807', low: '2798', close: '2805', in_position: true },
      ],
      markers: [
        ...fills.map((item, index) => ({
          native_trade_id: item.native_trade_id, at: '2026-02-02T09:10:00+08:00', event_at: item.modeled_fill_at,
          kind: index === 2 ? 'EXIT' : 'ENTRY', price: item.price,
        })),
        { trade_id: 'trade-on-page-2', at: '2026-02-02T15:00:00+08:00', kind: 'VALUATION', price: '2807' },
      ],
    } })
    return route.fulfill({ status: 404, json: { detail: { code: 'NOT_FOUND' } } })
  })

  await page.goto('/backtests')
  await page.getByRole('link', { name: 'rollover-run', exact: true }).first().click()
  await page.getByRole('button', { name: '交易明细' }).click()
  await page.getByRole('button', { name: 'rollover-A' }).click()
  const replay = page.getByRole('region', { name: /逐笔回放 · FU2603/ })
  await expect(replay.getByText('原修订的归档图窗不可重建。')).toBeVisible()
  await expect(replay.getByRole('img')).toHaveCount(0)
  await expect(replay.getByText('换月中断')).toBeVisible()
  await expect(replay.getByText('估值合约')).toBeVisible()
  await expect(replay.getByRole('definition').filter({ hasText: /^FU2603$/ })).toBeVisible()
  await expect(replay.getByText('2807', { exact: true })).toBeVisible()
  await expect(replay.getByText('35', { exact: true })).toBeVisible()
  await expect(replay.getByText('12', { exact: true })).toBeVisible()
  const executions = replay.getByRole('table', { name: '成交时钟与对账' })
  await expect(executions.getByRole('row')).toHaveCount(4)
  await expect(executions.getByRole('row').filter({ hasText: 'open-2' }).getByRole('cell', { name: '2 手' })).toBeVisible()
  await expect(executions.getByRole('row').filter({ hasText: 'close-1' }).getByRole('cell', { name: '1 手' })).toBeVisible()

  newest = 'new-run'
  await page.getByRole('button', { name: '刷新状态' }).click()
  await page.getByRole('button', { name: '下一页' }).click()
  await expect(page.getByRole('button', { name: 'trade-on-page-2' })).toBeVisible()
  await expect(replay.getByText('2807', { exact: true })).toBeVisible()
  await expect(page).toHaveURL(/\/backtests\/rollover-run$/)
  await page.getByRole('button', { name: 'trade-on-page-2' }).click()
  await expect(replay.locator('canvas').first()).toBeVisible()
  const markers = replay.getByRole('list', { name: '图上成交与估值标记' })
  await expect(markers.getByRole('listitem')).toHaveCount(4)
  for (const label of ['进场 · 1 手 · 2801', '进场 · 2 手 · 2801', '出场 · 1 手 · 2801', '估值 · 2807']) {
    await expect(markers.getByText(label, { exact: true })).toBeVisible()
  }
  expect(requests.every(([method, path]) => method === 'GET' && !path.includes('new-run'))).toBe(true)
})

test('persists unconfirmed rerun keys across reload and reads bounded task events', async ({ page }) => {
  const rerunKeys = []
  await page.route('**/api/v1/backtests/runs/**', async route => {
    const path = new URL(route.request().url()).pathname.replace('/api/v1/backtests', '')
    if (path === '/runs/source') return route.fulfill({ json: run('source', 'CANCELED') })
    if (path === '/runs/source/events') return route.fulfill({ json: {
      run_id: 'source', items: [
        { at: '2026-11-28T11:02:00+08:00', status: 'QUEUED', phase: 'QUEUED' },
        { at: '2026-11-28T11:03:00+08:00', status: 'CANCELED', phase: 'ENGINE_STOPPED' },
      ],
    } })
    if (path === '/runs/source/rerun') {
      rerunKeys.push(route.request().postDataJSON().request_key)
      if (rerunKeys.length === 1) return route.fulfill({ status: 202, json: {} })
      return route.fulfill({ status: 202, json: { ...run('retry', 'QUEUED'), source_run_id: 'source' } })
    }
    if (path === '/runs/retry') return route.fulfill({ json: { ...run('retry', 'QUEUED'), source_run_id: 'source' } })
    if (path === '/runs/retry/events') return route.fulfill({ json: { run_id: 'retry', items: [] } })
    return route.fulfill({ status: 404, json: { detail: { code: 'NOT_FOUND' } } })
  })

  await page.goto('/backtests/source')
  await page.getByText('任务日志 （最近 2 条）').click()
  const events = page.getByRole('list', { name: '任务状态事件' })
  await expect(events.getByRole('listitem')).toHaveCount(2)
  await expect(events.getByText(/已取消 · ENGINE_STOPPED/)).toBeVisible()
  await page.getByRole('button', { name: '按原配置重跑' }).click()
  await expect(page.getByRole('alert')).toContainText('重跑提交未确认')
  await page.reload()
  await page.getByRole('button', { name: '按原配置重跑' }).click()
  await expect(page).toHaveURL(/\/backtests\/retry$/)
  expect(rerunKeys).toHaveLength(2)
  expect(rerunKeys[0]).toBe(rerunKeys[1])
  await page.getByRole('link', { name: '来源 Run source' }).click()
  await page.getByRole('button', { name: '按原配置重跑' }).click()
  await expect(page).toHaveURL(/\/backtests\/retry$/)
  expect(rerunKeys[2]).not.toBe(rerunKeys[0])
})
