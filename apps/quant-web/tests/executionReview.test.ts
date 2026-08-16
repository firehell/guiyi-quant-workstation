import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { describe, it } from 'node:test'

import {
  ExecutionReviewApiError,
  createExecutionReviewApi,
  executionReviewErrorMessage,
  refreshDispositionCorrectionState,
  toExecutionReviewApiError,
} from '../src/api/executionReview.ts'
import {
  applyNeutralSelection,
  buildExecutedDispositionCorrectionRequest,
  buildReviewItemFilters,
  buildStatsFilters,
  defaultExecutionQuantity,
  executionReviewActionLabel,
  formatExecutionReviewRate,
  initialReconstructionMode,
  timelineForDisplay,
  MANUAL_EXECUTION_TYPES,
  validateExecutedDraft,
  validateNotExecutedDraft,
  validateReviewDraft,
} from '../src/utils/executionReview.ts'

const executionStatsSource = readFileSync(
  new URL('../src/components/execution-review/ExecutionStats.vue', import.meta.url),
  'utf8',
)

function fakeHttp(response: unknown = {}) {
  const calls: Array<{ method: string; url: string; config?: unknown; body?: unknown }> = []
  return {
    calls,
    client: {
      get: async (url: string, config?: unknown) => {
        calls.push({ method: 'GET', url, config })
        return response
      },
      post: async (url: string, body?: unknown) => {
        calls.push({ method: 'POST', url, body })
        return response
      },
      put: async (url: string, body?: unknown) => {
        calls.push({ method: 'PUT', url, body })
        return response
      },
    },
  }
}

describe('Execution Review HTTP adapter', () => {
  it('always sends the required items state and only done date filters', async () => {
    const http = fakeHttp({ items: [] })
    const api = createExecutionReviewApi(http.client)

    await api.listItems({
      state: 'done',
      symbol: 'jm',
      start_trading_day: '2026-08-01',
      end_trading_day: '2026-08-15',
    })

    assert.equal(http.calls[0].url, '/api/execution-review/items')
    assert.deepEqual(http.calls[0].config, { params: {
      state: 'done',
      symbol: 'jm',
      start_trading_day: '2026-08-01',
      end_trading_day: '2026-08-15',
    } })
  })

  it('serializes event ids as repeated unbracketed query parameters', async () => {
    const http = fakeHttp({ items: [] })
    const api = createExecutionReviewApi(http.client)

    await api.getEventStates([12, 15])

    const params = (http.calls[0].config as { params: URLSearchParams }).params
    assert.equal(params.toString(), 'event_ids=12&event_ids=15')
  })

  it('sends explicit signal and full reconstruction modes', async () => {
    const http = fakeHttp({})
    const api = createExecutionReviewApi(http.client)

    await api.getReconstruction(17, 'signal')
    await api.getReconstruction(17, 'full')

    assert.deepEqual(http.calls.map((call) => call.config), [
      { params: { mode: 'signal' } },
      { params: { mode: 'full' } },
    ])
  })

  it('covers every formal mutation path without changing payloads', async () => {
    const http = fakeHttp({})
    const api = createExecutionReviewApi(http.client)
    const payload = { note: '人工事实' }

    await api.recordNotExecuted(1, payload as never)
    await api.recordExecuted(2, payload as never)
    await api.appendExecution(3, payload as never)
    await api.submitReview(4, payload as never)
    await api.updateDecision(5, payload as never)
    await api.updateExecution(6, payload as never)
    await api.replaceExecutionTimeline(7, payload as never)
    await api.updateReview(8, payload as never)
    await api.correctDisposition(9, payload as never)

    assert.deepEqual(http.calls.map((call) => `${call.method} ${call.url}`), [
      'POST /api/execution-review/events/1/not-executed',
      'POST /api/execution-review/events/2/executed',
      'POST /api/execution-review/episodes/3/executions',
      'POST /api/execution-review/episodes/4/review',
      'PUT /api/execution-review/decisions/5',
      'PUT /api/execution-review/executions/6',
      'PUT /api/execution-review/episodes/7/execution-timeline',
      'PUT /api/execution-review/reviews/8',
      'POST /api/execution-review/decisions/9/correct-disposition',
    ])
    assert.ok(http.calls.every((call) => call.body === payload))
  })

  it('builds EXECUTED disposition correction facts without sending direction', () => {
    const body = buildExecutedDispositionCorrectionRequest({
      executed_at: '2026-08-15T10:30:00.000Z',
      price: '2300.5',
      quantity: 2,
      execution_reason_tags: ['KEY_LEVEL_BREAKOUT'],
      planned_stop_price: '2288.5',
      stop_basis: 'PREVIOUS_BAR_EXTREME',
      note: 'manual correction',
    })

    assert.deepEqual(body, {
      target_disposition: 'EXECUTED',
      executed_at: '2026-08-15T10:30:00.000Z',
      price: '2300.5',
      quantity: 2,
      execution_reason_tags: ['KEY_LEVEL_BREAKOUT'],
      planned_stop_price: '2288.5',
      stop_basis: 'PREVIOUS_BAR_EXTREME',
      note: 'manual correction',
    })
    assert.equal('direction' in body, false)
  })

  it('refreshes correction workflow state only from the corrected Event state', async () => {
    const response = {
      decision: { alert_event_id: 42 },
      episode: { id: 7, closed_at: null },
      execution: { execution_type: 'ADD' },
    }
    const calls: number[][] = []

    const eventState = await refreshDispositionCorrectionState(response as never, async (eventIds) => {
      calls.push(eventIds)
      return { items: [{ event_id: 42, state: 'pending_review', decision_id: 9, episode_id: 7 }] }
    })

    assert.deepEqual(calls, [[42]])
    assert.deepEqual(eventState, {
      event_id: 42,
      state: 'pending_review',
      decision_id: 9,
      episode_id: 7,
    })
  })

  it('does not derive correction workflow state from Episode closed_at', async () => {
    for (const [closedAt, authoritativeState] of [
      [null, 'done'],
      ['2026-08-15T04:00:00Z', 'open'],
    ] as const) {
      const eventState = await refreshDispositionCorrectionState({
        decision: { alert_event_id: 42 },
        episode: { id: 7, closed_at: closedAt },
      } as never, async () => ({
        items: [{ event_id: 42, state: authoritativeState, decision_id: 9, episode_id: 7 }],
      }))

      assert.equal(eventState.state, authoritativeState)
    }
  })
})

describe('Execution Review safe errors', () => {
  it('extracts only the trusted detail code and HTTP status', () => {
    const error = toExecutionReviewApiError({
      response: {
        status: 409,
        data: { detail: { code: 'OPPOSITE_EPISODE_OPEN', sql: 'secret' }, traceback: '/tmp/private.py' },
      },
      message: 'raw axios secret',
    })

    assert.ok(error instanceof ExecutionReviewApiError)
    assert.equal(error.code, 'OPPOSITE_EPISODE_OPEN')
    assert.equal(error.httpStatus, 409)
    assert.equal(error.message, 'OPPOSITE_EPISODE_OPEN')
    assert.equal(executionReviewErrorMessage(error), '当前已有反方向交易记录，请先完成原交易')
  })

  it('redacts malformed and unknown errors to one safe message', () => {
    const error = toExecutionReviewApiError({
      response: { status: 503, data: { detail: '/Users/private/sql SELECT *' } },
      stack: 'secret stack',
    })

    assert.equal(error.code, 'UNKNOWN')
    assert.equal(error.httpStatus, 503)
    assert.equal(executionReviewErrorMessage(error), '操作暂未完成，请刷新后重试')
  })
})

describe('Execution Review presentation contracts', () => {
  it('maps the four backend states to their fixed Market actions', () => {
    assert.deepEqual([
      executionReviewActionLabel('pending_decision'),
      executionReviewActionLabel('open'),
      executionReviewActionLabel('pending_review'),
      executionReviewActionLabel('done'),
    ], ['记录执行', '查看交易', '去复盘', '查看记录'])
  })

  it('validates NOT_EXECUTED and EXECUTED inputs without choosing direction or topology', () => {
    assert.deepEqual(validateNotExecutedDraft({ primary_reason: '', secondary_reasons: [], note: '' }), ['请选择主要原因'])
    assert.deepEqual(validateNotExecutedDraft({ primary_reason: 'TOO_LATE', secondary_reasons: [], note: '' }), [])
    assert.deepEqual(validateExecutedDraft({
      executed_at: '', price: '', quantity: null, execution_reason_tags: [],
      planned_stop_price: null, stop_basis: null, note: '',
    }), ['请填写成交时间', '请填写有效成交价', '请填写有效手数', '请至少选择一个执行原因'])
    assert.deepEqual(validateExecutedDraft({
      executed_at: '2026-08-15T10:30', price: '1234.50000000', quantity: 2,
      execution_reason_tags: ['KEY_LEVEL_BREAKOUT'], planned_stop_price: null,
      stop_basis: null, note: '',
    }), [])
  })

  it('keeps CLOSE as a backend-submitted quantity default without position arithmetic', () => {
    assert.deepEqual(MANUAL_EXECUTION_TYPES, ['ADD', 'REDUCE', 'CLOSE'])
    assert.equal(defaultExecutionQuantity('CLOSE', 7, 2), 7)
    assert.equal(defaultExecutionQuantity('REDUCE', 7, 2), 2)
  })

  it('keeps stats dates independent from workflow state while preserving active work queues', () => {
    const filters = {
      symbol: ' jm ', direction: 'LONG' as const, frequency: '5m' as const,
      start_trading_day: '2026-08-01', end_trading_day: '2026-08-15',
    }
    for (const state of ['pending_decision', 'open', 'pending_review'] as const) {
      assert.deepEqual(buildReviewItemFilters(state, filters), {
        state, symbol: 'jm', direction: 'LONG', frequency: '5m',
      })
    }
    assert.deepEqual(buildReviewItemFilters('done', filters), {
      state: 'done', symbol: 'jm', direction: 'LONG', frequency: '5m',
      start_trading_day: '2026-08-01', end_trading_day: '2026-08-15',
    })
    assert.deepEqual(buildStatsFilters(filters), {
      symbol: 'jm', direction: 'LONG', frequency: '5m',
      trading_day_from: '2026-08-01', trading_day_to: '2026-08-15',
    })
    assert.deepEqual(buildStatsFilters({
      ...filters, start_trading_day: '', end_trading_day: '',
    }), {
      symbol: 'jm', direction: 'LONG', frequency: '5m',
    })
  })

  it('formats backend rates with exactly one decimal without recomputing counts', () => {
    assert.equal(formatExecutionReviewRate('0.8'), '80.0%')
    assert.equal(formatExecutionReviewRate('0.375'), '37.5%')
    assert.equal(formatExecutionReviewRate(null), '—')
  })

  it('renders backend primary reason counts without consuming secondary reasons', () => {
    assert.match(executionStatsSource, /主要未执行原因/)
    assert.match(executionStatsSource, /stats\.opportunities\.primary_reason_counts/)
    assert.doesNotMatch(executionStatsSource, /secondary_reasons/)
  })

  it('enforces neutral tag affordances and all five review groups', () => {
    assert.deepEqual(applyNeutralSelection(['TOO_EARLY'], 'REASONABLE', 'REASONABLE'), ['REASONABLE'])
    assert.deepEqual(applyNeutralSelection(['REASONABLE'], 'TOO_LATE', 'REASONABLE'), ['TOO_LATE'])
    assert.deepEqual(applyNeutralSelection(['FOMO'], 'NONE', 'NONE'), ['NONE'])
    assert.equal(validateReviewDraft({
      signal_execution_adherence: 'ALIGNED', entry_tags: ['REASONABLE'],
      holding_tags: ['NORMAL'], exit_tags: ['NORMAL'],
      market_context_tags: ['RANGE'], psychology_tags: ['NONE'], summary: '',
    }).length, 0)
    assert.equal(validateReviewDraft({
      signal_execution_adherence: '', entry_tags: [], holding_tags: [], exit_tags: [],
      market_context_tags: [], psychology_tags: [], summary: '',
    }).length, 6)
  })

  it('defaults reconstruction to signal and never fabricates a roll CLOSE', () => {
    assert.equal(initialReconstructionMode(), 'signal')
    const executions = [{ id: 1, execution_type: 'OPEN' }]
    assert.equal(timelineForDisplay(executions, {
      close_reason: 'DOMINANT_ROLL',
      roll_reference_exit_price: '2310.50000000',
      roll_reference_bar_end: '2026-08-15T07:00:00Z',
    }), executions)
  })
})
