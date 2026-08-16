import { expect, test } from '@playwright/test'

const eventId = 17
const episodeId = 45

function eventContext(overrides = {}) {
  return {
    id: eventId,
    rule_code: 'subing_entry_signal_v1',
    symbol: 'jm',
    contract: 'JM2609',
    trading_day: '2026-08-15',
    frequency: '5m',
    bar_end: '2026-08-15T02:25:00Z',
    result_codes: ['buy'],
    lower_tf_confirmation: true,
    detected_at: '2026-08-15T02:26:00Z',
    notification_attempted_at: null,
    ...overrides,
  }
}

function decision(overrides = {}) {
  return {
    id: 31,
    alert_event_id: eventId,
    disposition: 'EXECUTED',
    first_viewed_at: null,
    decided_at: '2026-08-15T02:30:00Z',
    primary_not_execute_reason: null,
    secondary_not_execute_reasons: [],
    note: null,
    execution_reason_tags: ['KEY_LEVEL_BREAKOUT'],
    planned_stop_price: null,
    stop_basis: null,
    ...overrides,
  }
}

function episode(overrides = {}) {
  return {
    id: episodeId,
    origin_decision_id: 31,
    symbol: 'jm',
    contract: 'JM2609',
    direction: 'LONG',
    opened_at: '2026-08-15T02:30:00Z',
    closed_at: null,
    close_reason: null,
    roll_reference_exit_price: null,
    roll_reference_bar_end: null,
    contract_multiplier_snapshot: '60.00000000',
    multiplier_policy_id: 'cn_futures_multiplier_v1',
    ...overrides,
  }
}

function execution(overrides = {}) {
  return {
    id: 51,
    episode_id: episodeId,
    trigger_decision_id: 31,
    sequence_no: 1,
    execution_type: 'OPEN',
    executed_at: '2026-08-15T02:30:00Z',
    price: '2300.00000000',
    quantity: 2,
    note: null,
    ...overrides,
  }
}

function position(overrides = {}) {
  return {
    remaining_quantity: 2,
    average_cost: '2300.00000000',
    realized_points: '0E-8',
    estimated_gross_pnl: '0E-8',
    ...overrides,
  }
}

function detail(overrides = {}) {
  return {
    episode: episode(),
    origin_event: eventContext(),
    decisions: [decision()],
    executions: [execution()],
    review: null,
    position: position(),
    ...overrides,
  }
}

function item(state, overrides = {}) {
  return {
    item_kind: state === 'pending_decision' || overrides.notExecuted ? 'decision' : 'episode',
    state,
    event_id: eventId,
    decision_id: state === 'pending_decision' ? null : 31,
    episode_id: state === 'pending_decision' || overrides.notExecuted ? null : episodeId,
    symbol: 'jm',
    contract: 'JM2609',
    direction: 'LONG',
    trading_day: '2026-08-15',
    ...overrides,
  }
}

function reconstruction(mode = 'signal', unavailable = false) {
  return {
    status: unavailable ? 'UNAVAILABLE' : 'READY',
    reason: unavailable ? 'MARKET_PARTITION_UNAVAILABLE' : null,
    mode,
    post_hoc_reconstruction: true,
    event: eventContext(),
    segment: unavailable ? null : {
      contract: 'JM2609', start_trading_day: '2026-08-01', end_trading_day: '2026-08-15',
    },
    window: unavailable ? null : {
      start_trading_day: mode === 'signal' ? '2026-08-15' : '2026-08-01',
      end_trading_day: '2026-08-15',
      bar_end_cutoff: mode === 'signal' ? '2026-08-15T02:25:00Z' : null,
    },
    bars_5m: unavailable ? [] : [{
      bar_end: '2026-08-15T02:25:00Z', trading_day: '2026-08-15',
      open: 2298, high: 2302, low: 2296, close: 2300,
      volume: 100, turnover: 1000, open_interest: 200,
    }],
    bars_15m: [],
  }
}

async function mockExecutionReview(page, options = {}) {
  const store = {
    state: options.state || 'pending_decision',
    item: options.item || null,
    detail: options.detail || detail(),
    reconstructionUnavailable: options.reconstructionUnavailable || false,
    executedType: options.executedType || 'OPEN',
    executedErrorCode: options.executedErrorCode || null,
    requests: [],
    timelineBody: null,
  }

  await page.route('**/api/execution-review/**', async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    const path = url.pathname
    store.requests.push(`${request.method()} ${path}${url.search}`)

    if (request.method() === 'GET' && path.endsWith('/items')) {
      const requestedState = url.searchParams.get('state')
      const current = store.item || item(store.state, { notExecuted: options.notExecuted })
      return route.fulfill({ json: { items: !options.emptyItems && requestedState === store.state ? [current] : [] } })
    }
    if (request.method() === 'GET' && path.endsWith('/event-states')) {
      return route.fulfill({ json: { items: [{
        event_id: eventId, state: store.state, decision_id: 31,
        episode_id: store.state === 'done' ? episodeId : null,
      }] } })
    }
    if (request.method() === 'GET' && path.endsWith(`/episodes/${episodeId}`)) {
      return route.fulfill({ json: store.detail })
    }
    if (request.method() === 'GET' && path.endsWith(`/events/${eventId}/reconstruction`)) {
      return route.fulfill({ json: reconstruction(url.searchParams.get('mode') || 'signal', store.reconstructionUnavailable) })
    }
    if (request.method() === 'POST' && path.endsWith(`/events/${eventId}/not-executed`)) {
      store.state = 'done'
      store.item = item('done', { notExecuted: true })
      return route.fulfill({ status: 201, json: decision({ disposition: 'NOT_EXECUTED', primary_not_execute_reason: 'TOO_LATE' }) })
    }
    if (request.method() === 'POST' && path.endsWith(`/events/${eventId}/executed`)) {
      if (store.executedErrorCode) {
        return route.fulfill({ status: 409, json: { detail: { code: store.executedErrorCode } } })
      }
      store.state = 'open'
      store.item = item('open')
      return route.fulfill({ status: 201, json: {
        decision: decision(), episode: store.detail.episode,
        execution: execution({ execution_type: store.executedType }), position: store.detail.position,
      } })
    }
    if (request.method() === 'POST' && path.endsWith(`/episodes/${episodeId}/executions`)) {
      const body = request.postDataJSON()
      const close = execution({
        id: 52, trigger_decision_id: null, sequence_no: 2,
        execution_type: body.execution_type, executed_at: body.executed_at,
        price: body.price, quantity: body.quantity,
      })
      store.detail = {
        ...store.detail,
        episode: episode({ closed_at: body.executed_at, close_reason: 'EXECUTION_NET_ZERO' }),
        executions: [...store.detail.executions, close],
        position: position({ remaining_quantity: 0, average_cost: null, realized_points: '20.00000000', estimated_gross_pnl: '1200.00000000' }),
      }
      store.state = 'pending_review'
      store.item = item('pending_review')
      return route.fulfill({ status: 201, json: {
        episode: store.detail.episode, execution: close, position: store.detail.position,
      } })
    }
    if (request.method() === 'POST' && path.endsWith(`/episodes/${episodeId}/review`)) {
      const body = request.postDataJSON()
      const review = {
        id: 71, episode_id: episodeId, ...body,
        submitted_at: '2026-08-15T08:00:00Z', updated_at: '2026-08-15T08:00:00Z',
      }
      store.detail = { ...store.detail, review }
      store.state = 'done'
      store.item = item('done')
      return route.fulfill({ status: 201, json: review })
    }
    if (request.method() === 'PUT' && path.endsWith(`/episodes/${episodeId}/execution-timeline`)) {
      store.timelineBody = request.postDataJSON()
      const last = store.timelineBody.items.at(-1)
      const rebuilt = store.timelineBody.items.map((row, index) => execution({
        id: row.execution_id || 50 + index + 1,
        trigger_decision_id: index === 0 ? 31 : null,
        sequence_no: index + 1,
        execution_type: row.execution_type,
        executed_at: row.executed_at,
        price: row.price,
        quantity: row.quantity,
      }))
      store.detail = {
        ...store.detail,
        episode: episode({ closed_at: last.executed_at, close_reason: 'EXECUTION_NET_ZERO' }),
        executions: rebuilt,
        position: position({ remaining_quantity: 0, average_cost: null }),
      }
      return route.fulfill({ json: {
        episode: store.detail.episode, executions: rebuilt, position: store.detail.position,
      } })
    }
    if (request.method() === 'PUT' || request.method() === 'POST') {
      return route.fulfill({ json: {} })
    }
    return route.fulfill({ status: 404, json: { detail: { code: 'TEST_ROUTE_MISSING' } } })
  })
  return store
}

async function selectFirst(page, testId) {
  await page.getByTestId(testId).click()
  await page.keyboard.press('ArrowDown')
  await page.keyboard.press('Enter')
}

async function fillExecuted(page) {
  await page.getByTestId('decision-executed-at').fill('2026-08-15T10:30')
  await page.getByTestId('decision-price').fill('2300.5')
  await page.getByTestId('decision-quantity').fill('2')
  await selectFirst(page, 'decision-execution-reasons')
}

async function fillReview(page) {
  for (const testId of [
    'review-adherence', 'review-entry', 'review-holding', 'review-exit',
    'review-market-context', 'review-psychology',
  ]) await selectFirst(page, testId)
}

test('pending decision records NOT_EXECUTED and moves to done', async ({ page }) => {
  await mockExecutionReview(page)
  await page.goto(`/trade-records?state=pending_decision&event_id=${eventId}`)

  await expect(page.getByRole('heading', { name: '交易记录' })).toBeVisible()
  await page.getByRole('button', { name: '未执行', exact: true }).click()
  await selectFirst(page, 'not-executed-primary')
  await page.getByRole('button', { name: '记录未执行' }).click()

  await expect(page.getByText('已记录为未执行')).toBeVisible()
  await expect(page).toHaveURL(/state=done/)
  await expect(page.getByText('已完成 1', { exact: true })).toBeVisible()
})

test('EXECUTED OPEN then real CLOSE then structured Review reaches done', async ({ page }) => {
  await mockExecutionReview(page)
  await page.goto(`/trade-records?state=pending_decision&event_id=${eventId}`)
  await page.getByRole('button', { name: '已执行', exact: true }).click()
  await fillExecuted(page)
  await page.getByRole('button', { name: '记录实际执行' }).click()
  await expect(page.getByText('已记录开仓')).toBeVisible()

  await page.getByRole('button', { name: 'CLOSE', exact: true }).click()
  await page.getByTestId('execution-at').fill('2026-08-15T11:00')
  await page.getByTestId('execution-price').fill('2310.5')
  await expect(page.getByTestId('execution-quantity')).toHaveValue('2')
  await page.getByRole('button', { name: '保存执行记录' }).click()
  await expect(page).toHaveURL(/state=pending_review/)

  await fillReview(page)
  await page.getByRole('button', { name: '提交复盘' }).click()
  await expect(page.getByText('复盘已保存')).toBeVisible()
  await expect(page).toHaveURL(/state=done/)
})

test('same-direction later Event trusts backend ADD response', async ({ page }) => {
  await mockExecutionReview(page, { executedType: 'ADD' })
  await page.goto(`/trade-records?state=pending_decision&event_id=${eventId}`)
  await page.getByRole('button', { name: '已执行', exact: true }).click()
  await fillExecuted(page)
  await page.getByRole('button', { name: '记录实际执行' }).click()

  await expect(page.getByText('已记录为同方向加仓')).toBeVisible()
})

test('opposite Event is hard blocked without close-and-reverse affordance', async ({ page }) => {
  const store = await mockExecutionReview(page, { executedErrorCode: 'OPPOSITE_EPISODE_OPEN' })
  await page.goto(`/trade-records?state=pending_decision&event_id=${eventId}`)
  await page.getByRole('button', { name: '已执行', exact: true }).click()
  await fillExecuted(page)
  await page.getByRole('button', { name: '记录实际执行' }).click()

  await expect(page.getByText('当前已有反方向交易记录，请先完成原交易')).toBeVisible()
  await expect(page.getByText(/反手/)).toHaveCount(0)
  await expect.poll(() => store.requests.filter((value) => value.startsWith('GET /api/execution-review/items')).length).toBeGreaterThan(4)
})

test('DOMINANT_ROLL is an estimate and actual CLOSE uses full timeline correction', async ({ page }) => {
  const rolled = detail({
    episode: episode({
      closed_at: '2026-08-15T07:00:00Z', close_reason: 'DOMINANT_ROLL',
      roll_reference_exit_price: '2310.50000000', roll_reference_bar_end: '2026-08-15T07:00:00Z',
    }),
  })
  const store = await mockExecutionReview(page, { state: 'done', detail: rolled })
  await page.goto(`/trade-records?state=done&event_id=${eventId}`)

  await expect(page.getByText('主力换月自动结束')).toBeVisible()
  await expect(page.getByText('系统估算 · 非真实成交')).toBeVisible()
  await expect(page.getByTestId('execution-timeline').getByText('CLOSE', { exact: true })).toHaveCount(0)
  await page.getByRole('button', { name: '纠正执行记录' }).click()
  await page.getByRole('button', { name: '添加真实 CLOSE' }).click()
  await page.getByTestId('timeline-time-1').fill('2026-08-15T15:30')
  await page.getByTestId('timeline-price-1').fill('2312.5')
  await page.getByTestId('timeline-quantity-1').fill('2')
  await page.getByRole('button', { name: '提交完整执行时间线' }).click()

  await expect.poll(() => store.timelineBody?.items.at(-1)?.execution_type).toBe('CLOSE')
  await expect(page.getByText('系统估算 · 非真实成交')).toHaveCount(0)
})

test('reconstruction defaults signal and switches to full only explicitly', async ({ page }) => {
  const store = await mockExecutionReview(page)
  await page.goto(`/trade-records?state=pending_decision&event_id=${eventId}`)

  await expect(page.getByTestId('reconstruction-panel')).toContainText('信号当时')
  expect(store.requests.some((value) => value.includes('mode=signal'))).toBe(true)
  await page.getByRole('button', { name: '完整走势' }).click()
  await expect.poll(() => store.requests.some((value) => value.includes('mode=full'))).toBe(true)
  await expect(page.getByTestId('reconstruction-panel')).toContainText('事后历史重建')
})

test('unavailable reconstruction never blocks Review submission', async ({ page }) => {
  const closed = detail({
    episode: episode({ closed_at: '2026-08-15T04:00:00Z', close_reason: 'EXECUTION_NET_ZERO' }),
    executions: [execution(), execution({
      id: 52, trigger_decision_id: null, sequence_no: 2, execution_type: 'CLOSE',
      executed_at: '2026-08-15T04:00:00Z', price: '2310.00000000', quantity: 2,
    })],
    position: position({ remaining_quantity: 0, average_cost: null }),
  })
  await mockExecutionReview(page, { state: 'pending_review', detail: closed, reconstructionUnavailable: true })
  await page.goto(`/trade-records?state=pending_review&episode_id=${episodeId}`)

  await expect(page.getByText('历史行情暂不可重建')).toBeVisible()
  await fillReview(page)
  await page.getByRole('button', { name: '提交复盘' }).click()
  await expect(page.getByText('复盘已保存')).toBeVisible()
})

test('done deep-link resolves a non-origin trigger Event through event state lineage', async ({ page }) => {
  const completed = detail({
    episode: episode({ closed_at: '2026-08-15T04:00:00Z', close_reason: 'EXECUTION_NET_ZERO' }),
    executions: [execution(), execution({
      id: 52, trigger_decision_id: null, sequence_no: 2, execution_type: 'CLOSE',
      executed_at: '2026-08-15T04:00:00Z', price: '2310.00000000', quantity: 2,
    })],
    review: {
      id: 71, episode_id: episodeId, signal_execution_adherence: 'ALIGNED',
      entry_tags: ['REASONABLE'], holding_tags: ['NORMAL'], exit_tags: ['NORMAL'],
      market_context_tags: ['RANGE'], psychology_tags: ['NONE'], summary: null,
      submitted_at: '2026-08-15T08:00:00Z', updated_at: '2026-08-15T08:00:00Z',
    },
    position: position({ remaining_quantity: 0, average_cost: null }),
  })
  await mockExecutionReview(page, { state: 'done', detail: completed, emptyItems: true })

  await page.goto(`/trade-records?state=done&event_id=${eventId}`)

  await expect(page.getByTestId('episode-detail')).toContainText('#45')
  await expect(page.getByTestId('episode-detail')).toContainText('已结束')
})

test('MarketFormalSignals batches event states and deep-links all four actions', async ({ page }) => {
  const signals = ['pending_decision', 'open', 'pending_review', 'done'].map((state, index) => ({
    ...eventContext({ id: eventId + index, symbol: ['jm', 'ag', 'au', 'rb'][index] }),
    display_name: '苏冰', product_name: ['焦煤', '白银', '黄金', '螺纹钢'][index],
  }))
  let eventStateQuery = ''
  await page.route('**/api/alerts/formal-signals/current', (route) => route.fulfill({ json: {
    status: 'ready', trading_day: '2026-08-15', items: signals,
  } }))
  await page.route('**/api/execution-review/event-states**', (route) => {
    eventStateQuery = new URL(route.request().url()).search
    return route.fulfill({ json: { items: ['pending_decision', 'open', 'pending_review', 'done'].map((state, index) => ({
      event_id: eventId + index, state, decision_id: index ? 31 + index : null,
      episode_id: state === 'open' || state === 'pending_review' || state === 'done' ? episodeId + index : null,
    })) } })
  })
  await page.route('**/api/execution-review/items**', (route) => route.fulfill({ json: { items: [] } }))
  await page.route('**/api/v1/market/research/radar', (route) => route.fulfill({ json: {
    status: 'ready', expected_as_of: '2026-08-15', active_count: 60, participant_count: 60,
    stale: [], unavailable: [], summary: { up_count: 0, down_count: 0, volume_expansion_count: 0, oi_increase_count: 0, high_volatility_count: 0 },
    items: [], attention: [], sector_summary: [],
  } }))
  await page.goto('/market')

  const formal = page.getByTestId('market-formal-signals')
  for (const label of ['记录执行', '查看交易', '去复盘', '查看记录']) {
    await expect(formal.getByRole('button', { name: label })).toBeVisible()
  }
  expect(eventStateQuery).toBe('?event_ids=17&event_ids=18&event_ids=19&event_ids=20')
  await formal.getByRole('button', { name: '去复盘' }).click()
  await expect(page).toHaveURL(/\/trade-records\?state=pending_review&episode_id=47/)
})

test('MarketFormalSignals stays visible with a safe action when review state is unavailable', async ({ page }) => {
  await page.route('**/api/alerts/formal-signals/current', (route) => route.fulfill({ json: {
    status: 'ready', trading_day: '2026-08-15',
    items: [{ ...eventContext(), display_name: '苏冰', product_name: '焦煤' }],
  } }))
  await page.route('**/api/execution-review/event-states**', (route) => route.fulfill({
    status: 503, json: { detail: { code: 'EXECUTION_REVIEW_PERSIST_FAILED' } },
  }))
  await page.route('**/api/v1/market/research/radar', (route) => route.fulfill({ json: {
    status: 'ready', expected_as_of: '2026-08-15', active_count: 60, participant_count: 60,
    stale: [], unavailable: [], summary: { up_count: 0, down_count: 0, volume_expansion_count: 0, oi_increase_count: 0, high_volatility_count: 0 },
    items: [], attention: [], sector_summary: [],
  } }))

  await page.goto('/market')

  const formal = page.getByTestId('market-formal-signals')
  await expect(formal).toContainText('JM 焦煤 · 买入信号')
  await expect(formal.getByRole('button', { name: '查看 →' })).toBeVisible()
  await expect(page.getByText('Market Radar', { exact: true })).toBeVisible()
})
