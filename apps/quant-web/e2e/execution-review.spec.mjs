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
    multiplier_policy_id: 'product_trade_multipliers_v1',
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

function stats() {
  return {
    opportunities: {
      eligible_events: 12,
      processed_events: 9,
      pending_events: 3,
      executed_decisions: 5,
      not_executed_decisions: 4,
      decision_completion_rate: '0.75000000',
      execution_rate: '0.55555556',
      primary_reason_counts: { TOO_LATE: 2, POOR_LOCATION: 1 },
    },
    episode_states: {
      open_episodes: 2,
      pending_review_episodes: 1,
      done_episodes: 6,
    },
    review_issue_top: {
      entry: { TOO_LATE: 2 },
      holding: { COULD_NOT_HOLD: 1 },
      exit_risk: { STOP_DELAYED: 1 },
      psychology: { HESITATION: 2 },
    },
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
    }, ...(mode === 'full' ? [{
      bar_end: '2026-08-15T02:30:00Z', trading_day: '2026-08-15',
      open: 2300, high: 2310, low: 2299, close: 2308,
      volume: 120, turnover: 1200, open_interest: 205,
    }] : [])],
    bars_15m: unavailable ? [] : [{
      bar_end: '2026-08-15T02:15:00Z', trading_day: '2026-08-15',
      open: 2290, high: 2301, low: 2288, close: 2298,
      volume: 280, turnover: 2800, open_interest: 198,
    }],
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
    correctionBody: null,
    correctionCalls: 0,
    requests: [],
    timelineBody: null,
  }

  await page.route('**/api/execution-review/**', async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    const path = url.pathname
    store.requests.push(`${request.method()} ${path}${url.search}`)

    if (request.method() === 'GET' && path.endsWith('/stats')) {
      if (options.statsError) {
        return route.fulfill({ status: 503, json: { detail: { code: 'STATS_UNAVAILABLE' } } })
      }
      return route.fulfill({ json: options.statsResponse || stats() })
    }
    if (request.method() === 'GET' && path.endsWith('/items')) {
      const requestedState = url.searchParams.get('state')
      const current = store.item || item(store.state, { notExecuted: options.notExecuted })
      return route.fulfill({ json: { items: !options.emptyItems && requestedState === store.state ? [current] : [] } })
    }
    if (request.method() === 'GET' && path.endsWith('/event-states')) {
      const current = store.item || item(store.state, { notExecuted: options.notExecuted })
      const requestedEventId = Number(url.searchParams.get('event_ids')) || eventId
      return route.fulfill({ json: { items: [{
        event_id: requestedEventId, state: store.state,
        decision_id: current.decision_id, episode_id: current.episode_id,
      }] } })
    }
    if (request.method() === 'GET' && path.endsWith(`/episodes/${episodeId}`)) {
      if (options.correctionRemovesEpisode && store.correctionCalls > 0) {
        return route.fulfill({ status: 404, json: { detail: { code: 'TRADE_EPISODE_NOT_FOUND' } } })
      }
      return route.fulfill({ json: store.detail })
    }
    if (request.method() === 'GET' && /\/events\/\d+\/reconstruction$/.test(path)) {
      const requestedEventId = Number(path.split('/').at(-2))
      const response = reconstruction(url.searchParams.get('mode') || 'signal', store.reconstructionUnavailable)
      response.event = eventContext({ id: requestedEventId })
      return route.fulfill({ json: response })
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
      if (options.appendErrorCode) {
        store.detail = {
          ...store.detail,
          episode: episode({ closed_at: '2026-08-15T04:00:00Z', close_reason: 'EXECUTION_NET_ZERO' }),
          executions: [...store.detail.executions, execution({
            id: 52, trigger_decision_id: null, sequence_no: 2, execution_type: 'CLOSE',
            executed_at: '2026-08-15T04:00:00Z', price: '2310.00000000', quantity: 2,
          })],
          position: position({ remaining_quantity: 0, average_cost: null }),
        }
        store.state = 'pending_review'
        store.item = item('pending_review')
        return route.fulfill({ status: 409, json: { detail: { code: options.appendErrorCode } } })
      }
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
    if (request.method() === 'POST' && /\/decisions\/\d+\/correct-disposition$/.test(path)) {
      const body = request.postDataJSON()
      const correctedDecisionId = Number(path.split('/').at(-2))
      const correctedEventId = options.correctionEventId || eventId
      store.correctionBody = body
      store.correctionCalls += 1
      if (options.correctionErrorCode) {
        if (options.correctionConflictState) {
          store.state = options.correctionConflictState
          store.item = item(store.state, {
            event_id: correctedEventId,
            decision_id: correctedDecisionId,
            notExecuted: store.state === 'done',
          })
        }
        return route.fulfill({ status: 409, json: { detail: { code: options.correctionErrorCode } } })
      }
      store.state = options.correctionEventState || (body.target_disposition === 'EXECUTED' ? 'open' : 'done')
      store.item = item(store.state, {
        event_id: correctedEventId,
        decision_id: correctedDecisionId,
        notExecuted: store.state === 'done' && body.target_disposition === 'NOT_EXECUTED',
      })
      if (options.correctionDetail) store.detail = options.correctionDetail
      const resultingEpisode = body.target_disposition === 'EXECUTED' || store.state !== 'done'
        ? store.detail.episode
        : null
      return route.fulfill({ json: {
        decision: decision({
          id: correctedDecisionId,
          alert_event_id: correctedEventId,
          disposition: body.target_disposition,
        }),
        episode: resultingEpisode,
        execution: body.target_disposition === 'EXECUTED'
          ? execution({
              trigger_decision_id: correctedDecisionId,
              execution_type: options.correctionExecutionType || 'OPEN',
            })
          : null,
        position: resultingEpisode ? store.detail.position : null,
      } })
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

async function fillExecutedCorrection(page) {
  await page.getByTestId('correction-executed-at').fill('2026-08-15T10:35')
  await page.getByTestId('correction-price').fill('2301.5')
  await page.getByTestId('correction-quantity').fill('2')
  await selectFirst(page, 'correction-execution-reasons')
}

async function chooseDispositionPrimary(page) {
  await selectFirst(page, 'disposition-primary')
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

  await expect(page.getByText('已记录为未执行', { exact: true })).toBeVisible()
  await expect(page).toHaveURL(/state=done/)
  await expect(page.getByText('已完成 1', { exact: true })).toBeVisible()
})

test('NOT_EXECUTED correction records execution facts and follows backend open state', async ({ page }) => {
  const store = await mockExecutionReview(page, { correctionEventState: 'open' })
  await page.goto(`/trade-records?state=pending_decision&event_id=${eventId}`)
  await selectFirst(page, 'not-executed-primary')
  await page.getByRole('button', { name: '记录未执行' }).click()

  await page.getByRole('button', { name: '纠错：改为已执行' }).click()
  await fillExecutedCorrection(page)
  await page.getByRole('button', { name: '提交处理结果纠错' }).click()

  await expect(page.getByText('处理结果已纠正，已记录开仓')).toBeVisible()
  await expect(page).toHaveURL(/state=open&episode_id=45/)
  await expect(page.getByTestId('episode-detail')).toBeVisible()
  expect(store.correctionBody.target_disposition).toBe('EXECUTED')
  expect(store.correctionBody.direction).toBeUndefined()
  expect(store.requests.some((value) => value.includes('GET /api/execution-review/event-states?event_ids=17'))).toBe(true)
})

test('NOT_EXECUTED correction shows ADD result but still follows backend EventState', async ({ page }) => {
  const closed = detail({
    episode: episode({ closed_at: '2026-08-15T04:00:00Z', close_reason: 'EXECUTION_NET_ZERO' }),
    position: position({ remaining_quantity: 0, average_cost: null }),
  })
  await mockExecutionReview(page, {
    state: 'done', notExecuted: true,
    correctionExecutionType: 'ADD', correctionEventState: 'pending_review',
    correctionDetail: closed,
  })
  await page.goto(`/trade-records?state=done&event_id=${eventId}`)

  await page.getByRole('button', { name: '纠错：改为已执行' }).click()
  await fillExecutedCorrection(page)
  await page.getByRole('button', { name: '提交处理结果纠错' }).click()

  await expect(page.getByText('处理结果已纠正，已记录为同方向加仓')).toBeVisible()
  await expect(page).toHaveURL(/state=pending_review&episode_id=45/)
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

test('later ADD disposition correction follows backend open state instead of forcing done', async ({ page }) => {
  const addDetail = detail({
    decisions: [decision(), decision({
      id: 32, alert_event_id: 18, decided_at: '2026-08-15T03:00:00Z',
    })],
    executions: [execution(), execution({
      id: 52, trigger_decision_id: 32, sequence_no: 2, execution_type: 'ADD',
      executed_at: '2026-08-15T03:00:00Z', price: '2305.00000000', quantity: 1,
    })],
    position: position({ remaining_quantity: 3, average_cost: '2301.66666667' }),
  })
  await mockExecutionReview(page, {
    state: 'open', detail: addDetail, correctionEventId: 18, correctionEventState: 'open',
  })
  await page.goto(`/trade-records?state=open&episode_id=${episodeId}`)

  await page.getByRole('button', { name: '编辑 Decision context' }).nth(1).click()
  await page.getByRole('button', { name: '纠正处理结果' }).click()
  await chooseDispositionPrimary(page)
  await page.getByRole('button', { name: '提交处理结果纠错' }).click()

  await expect(page).toHaveURL(/state=open&episode_id=45/)
  await expect(page.getByText('处理结果已纠正', { exact: true })).toBeVisible()
  await expect(page.getByTestId('episode-detail')).toContainText('进行中')
})

test('later ADD disposition correction follows backend pending_review state', async ({ page }) => {
  const addDetail = detail({
    decisions: [decision(), decision({ id: 32, alert_event_id: 18 })],
    executions: [execution(), execution({
      id: 52, trigger_decision_id: 32, sequence_no: 2, execution_type: 'ADD', quantity: 1,
    })],
  })
  const corrected = {
    ...addDetail,
    episode: episode({ closed_at: '2026-08-15T04:00:00Z', close_reason: 'EXECUTION_NET_ZERO' }),
    position: position({ remaining_quantity: 0, average_cost: null }),
  }
  await mockExecutionReview(page, {
    state: 'open', detail: addDetail, correctionEventId: 18,
    correctionEventState: 'pending_review', correctionDetail: corrected,
  })
  await page.goto(`/trade-records?state=open&episode_id=${episodeId}`)

  await page.getByRole('button', { name: '编辑 Decision context' }).nth(1).click()
  await page.getByRole('button', { name: '纠正处理结果' }).click()
  await chooseDispositionPrimary(page)
  await page.getByRole('button', { name: '提交处理结果纠错' }).click()

  await expect(page).toHaveURL(/state=pending_review&episode_id=45/)
})

test('correct-disposition 409 refreshes authoritative state without retrying mutation', async ({ page }) => {
  const store = await mockExecutionReview(page, {
    state: 'done', notExecuted: true,
    correctionErrorCode: 'DECISION_CORRECTION_CONFLICT', correctionConflictState: 'open',
  })
  await page.goto(`/trade-records?state=done&event_id=${eventId}`)

  await page.getByRole('button', { name: '纠错：改为已执行' }).click()
  await fillExecutedCorrection(page)
  await page.getByRole('button', { name: '提交处理结果纠错' }).click()

  await expect(page.getByText('已刷新后端最新状态')).toBeVisible()
  await expect(page).toHaveURL(/state=open&episode_id=45/)
  expect(store.correctionCalls).toBe(1)
})

test('Episode correction 409 follows the Decision Event after the old Episode disappears', async ({ page }) => {
  const addDetail = detail({
    decisions: [decision(), decision({ id: 32, alert_event_id: 18 })],
    executions: [execution(), execution({
      id: 52, trigger_decision_id: 32, sequence_no: 2, execution_type: 'ADD', quantity: 1,
    })],
  })
  const store = await mockExecutionReview(page, {
    state: 'open', detail: addDetail, correctionEventId: 18,
    correctionErrorCode: 'DECISION_CORRECTION_CONFLICT', correctionConflictState: 'done',
    correctionRemovesEpisode: true,
  })
  await page.goto(`/trade-records?state=open&episode_id=${episodeId}`)
  await expect(page.getByTestId('episode-detail')).toBeVisible()
  const initialEpisodeReads = store.requests.filter((value) => value.includes(`GET /api/execution-review/episodes/${episodeId}`)).length

  await page.getByRole('button', { name: '编辑 Decision context' }).nth(1).click()
  await page.getByRole('button', { name: '纠正处理结果' }).click()
  await chooseDispositionPrimary(page)
  await page.getByRole('button', { name: '提交处理结果纠错' }).click()

  await expect(page.getByText('已刷新后端最新状态')).toBeVisible()
  await expect(page).toHaveURL(/state=done&event_id=18/)
  expect(store.correctionCalls).toBe(1)
  expect(store.requests.some((value) => value.includes('GET /api/execution-review/event-states?event_ids=18'))).toBe(true)
  expect(store.requests.filter((value) => value.includes(`GET /api/execution-review/episodes/${episodeId}`))).toHaveLength(initialEpisodeReads)
})

test('unavailable reconstruction does not block NOT_EXECUTED correction', async ({ page }) => {
  await mockExecutionReview(page, {
    state: 'done', notExecuted: true, reconstructionUnavailable: true,
    correctionEventState: 'open',
  })
  await page.goto(`/trade-records?state=done&event_id=${eventId}`)

  await expect(page.getByText('历史行情暂不可重建')).toBeVisible()
  await page.getByRole('button', { name: '纠错：改为已执行' }).click()
  await fillExecutedCorrection(page)
  await page.getByRole('button', { name: '提交处理结果纠错' }).click()

  await expect(page).toHaveURL(/state=open&episode_id=45/)
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

test('409 while appending always reloads the authoritative EpisodeDetail', async ({ page }) => {
  await mockExecutionReview(page, { state: 'open', appendErrorCode: 'EPISODE_ALREADY_CLOSED' })
  await page.goto(`/trade-records?state=open&episode_id=${episodeId}`)
  await page.getByRole('button', { name: 'CLOSE', exact: true }).click()
  await page.getByTestId('execution-at').fill('2026-08-15T11:00')
  await page.getByTestId('execution-price').fill('2310.5')
  await page.getByRole('button', { name: '保存执行记录' }).click()

  await expect(page).toHaveURL(/state=pending_review/)
  await expect(page.getByTestId('episode-detail')).toContainText('已结束')
  await expect(page.getByTestId('execution-form')).toHaveCount(0)
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
  await expect(page.getByTestId('reconstruction-bars-5m')).toContainText('2300')
  await expect(page.getByTestId('reconstruction-bars-5m')).not.toContainText('2308')
  await expect(page.getByTestId('reconstruction-bars-15m')).toContainText('2298')
  expect(store.requests.some((value) => value.includes('mode=signal'))).toBe(true)
  await page.getByRole('button', { name: '完整走势' }).click()
  await expect.poll(() => store.requests.some((value) => value.includes('mode=full'))).toBe(true)
  await expect(page.getByTestId('reconstruction-panel')).toContainText('事后历史重建')
  await expect(page.getByTestId('reconstruction-bars-5m')).toContainText('2308')
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

test('missing multiplier explains unavailable RMB PnL without hiding review facts', async ({ page }) => {
  const completed = detail({
    episode: episode({
      closed_at: '2026-08-15T04:00:00Z',
      close_reason: 'EXECUTION_NET_ZERO',
      contract_multiplier_snapshot: null,
      multiplier_policy_id: null,
    }),
    executions: [execution(), execution({
      id: 52, trigger_decision_id: null, sequence_no: 2, execution_type: 'CLOSE',
      executed_at: '2026-08-15T04:00:00Z', price: '2306.25000000', quantity: 2,
    })],
    review: {
      id: 71, episode_id: episodeId, signal_execution_adherence: 'ALIGNED',
      entry_tags: ['REASONABLE'], holding_tags: ['NORMAL'], exit_tags: ['NORMAL'],
      market_context_tags: ['RANGE'], psychology_tags: ['NONE'], summary: null,
      submitted_at: '2026-08-15T08:00:00Z', updated_at: '2026-08-15T08:00:00Z',
    },
    position: position({
      remaining_quantity: 0,
      average_cost: null,
      realized_points: '12.50000000',
      estimated_gross_pnl: null,
    }),
  })
  await mockExecutionReview(page, { state: 'done', detail: completed })

  await page.goto(`/trade-records?state=done&event_id=${eventId}`)

  const episodeDetail = page.getByTestId('episode-detail')
  await expect(episodeDetail).toContainText('人民币估算不可用')
  await expect(episodeDetail).toContainText('该品种 multiplier 尚未核验')
  await expect(episodeDetail).toContainText('Realized points')
  await expect(episodeDetail).toContainText('12.50000000')
  await expect(episodeDetail).toContainText('剩余手数')
  await expect(episodeDetail).toContainText('平均成本')
  await expect(page.getByTestId('execution-timeline')).toBeVisible()
  await expect(episodeDetail).toContainText('结构化复盘')
})

test('stats keep their date range across tabs while active queues remain date-unfiltered', async ({ page }) => {
  const store = await mockExecutionReview(page, { state: 'done' })
  await page.goto('/trade-records?state=done')

  const panel = page.getByTestId('execution-stats')
  await expect(panel).toContainText('ExecutionStats / 执行复盘统计')
  await expect(panel).toContainText('符合机会12')
  await expect(panel).toContainText('决策完成率75.0%')
  await expect(panel).toContainText('待复盘1')
  await expect(panel.getByTestId('primary-reason-counts')).toContainText('主要未执行原因')
  await expect(panel.getByTestId('primary-reason-counts')).toContainText('TOO_LATE 2')
  await expect(panel.getByTestId('primary-reason-counts')).toContainText('POOR_LOCATION 1')
  await expect(page.getByText('全部可用历史（未设置交易日范围）')).toBeVisible()
  await page.getByPlaceholder('品种，例如 jm').fill(' jm ')
  await page.getByLabel('统计 / 已完成开始交易日').fill('2026-08-01')
  await page.getByLabel('统计 / 已完成结束交易日').fill('2026-08-15')
  store.requests.length = 0
  await page.getByRole('button', { name: '应用筛选' }).click()

  await expect.poll(() => store.requests.findLast((value) => value.startsWith('GET /api/execution-review/stats'))).toContain('symbol=jm')
  const latestStatsRequest = store.requests.findLast((value) => value.startsWith('GET /api/execution-review/stats'))
  expect(latestStatsRequest).toContain('trading_day_from=2026-08-01')
  expect(latestStatsRequest).toContain('trading_day_to=2026-08-15')

  for (const state of ['pending_decision', 'open', 'pending_review']) {
    await expect.poll(() => store.requests.some((value) => value.includes(`/items?state=${state}`))).toBe(true)
    const request = store.requests.find((value) => value.includes(`/items?state=${state}`))
    expect(request).not.toContain('start_trading_day')
    expect(request).not.toContain('end_trading_day')
  }
  await expect.poll(() => store.requests.some((value) => value.includes('/items?state=done'))).toBe(true)
  const doneRequest = store.requests.find((value) => value.includes('/items?state=done'))
  expect(doneRequest).toContain('start_trading_day=2026-08-01')
  expect(doneRequest).toContain('end_trading_day=2026-08-15')

  for (const tab of ['待决策 0', '进行中 0', '待复盘 0', '已完成 1']) {
    const previousStatsRequests = store.requests.filter((value) => value.startsWith('GET /api/execution-review/stats')).length
    await page.getByText(tab, { exact: true }).click()
    await expect.poll(() => store.requests.filter((value) => value.startsWith('GET /api/execution-review/stats')).length).toBeGreaterThan(previousStatsRequests)
    const request = store.requests.findLast((value) => value.startsWith('GET /api/execution-review/stats'))
    expect(request).toContain('trading_day_from=2026-08-01')
    expect(request).toContain('trading_day_to=2026-08-15')
    await expect(page.getByLabel('统计 / 已完成开始交易日')).toBeVisible()
    await expect(page.getByLabel('统计 / 已完成开始交易日')).toHaveValue('2026-08-01')
    await expect(page.getByLabel('统计 / 已完成结束交易日')).toBeVisible()
    await expect(page.getByLabel('统计 / 已完成结束交易日')).toHaveValue('2026-08-15')
  }
})

test('empty primary reason counts display 无 and ignore secondary reason data', async ({ page }) => {
  const response = stats()
  response.opportunities.primary_reason_counts = {}
  response.opportunities.secondary_reason_counts = { SECONDARY_ONLY: 9 }
  await mockExecutionReview(page, { statsResponse: response, emptyItems: true })
  await page.goto('/trade-records')

  const reasons = page.getByTestId('primary-reason-counts')
  await expect(reasons).toContainText('主要未执行原因')
  await expect(reasons).toContainText('无')
  await expect(reasons).not.toContainText('SECONDARY_ONLY')
})

test('stats failure remains local and does not hide the execution queue', async ({ page }) => {
  await mockExecutionReview(page, { state: 'open', statsError: true })
  await page.goto(`/trade-records?state=open&episode_id=${episodeId}`)

  await expect(page.getByTestId('execution-stats')).toContainText('统计暂不可用')
  await expect(page.getByText('进行中 1', { exact: true })).toBeVisible()
  await expect(page.getByTestId('episode-detail')).toBeVisible()
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
    status: 'ready', expected_as_of: '2026-08-15', target_as_of: '2026-08-15', data_as_of: '2026-08-15', freshness_state: 'current', freshness_message: '当前完整', active_count: 60, participant_count: 60,
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
    status: 'ready', expected_as_of: '2026-08-15', target_as_of: '2026-08-15', data_as_of: '2026-08-15', freshness_state: 'current', freshness_message: '当前完整', active_count: 60, participant_count: 60,
    stale: [], unavailable: [], summary: { up_count: 0, down_count: 0, volume_expansion_count: 0, oi_increase_count: 0, high_volatility_count: 0 },
    items: [], attention: [], sector_summary: [],
  } }))

  await page.goto('/market')

  const formal = page.getByTestId('market-formal-signals')
  await expect(formal).toContainText('JM 焦煤 · 买入信号')
  await expect(formal.getByRole('button', { name: '查看 →' })).toBeVisible()
  await expect(page.getByText('Market Radar', { exact: true })).toBeVisible()
})
