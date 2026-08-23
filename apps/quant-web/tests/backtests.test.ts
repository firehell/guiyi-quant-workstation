import assert from 'node:assert/strict'
import { describe, it } from 'node:test'

import type { AxiosAdapter, AxiosRequestConfig, AxiosResponse } from 'axios'

import {
  DEFAULT_BACKTEST_API_BASE_URL,
  artifactUrl,
  createBacktestClient,
  mapBacktestError,
  resolveBacktestApiBaseUrl,
  serializeBacktestRunRequest,
} from '../src/api/backtests.ts'
import type {
  BacktestHealth,
  BacktestRunForm,
  BacktestRunSummary,
} from '../src/types/backtest.ts'


const RUN_ID = '20260823T010203000000Z-0123456789abcdef'

const form: BacktestRunForm = {
  strategyId: 'example_future_smoke_v1',
  startDate: '2026-01-05',
  endDate: '2026-01-06',
  frequency: '1m',
  futureCash: '1000000.00',
  matchingType: 'next_bar',
  marginMultiplier: '1.00',
  futuresCommissionMultiplier: '1.00',
  slippageModel: 'PriceRatioSlippage',
  slippage: '0.0000',
  parameters: {
    order_book_id: 'IF1606',
    quantity: 2,
    risk_ratio: '0.0100',
    enabled: true,
  },
}

const runningRun: BacktestRunSummary = {
  run_id: RUN_ID,
  research_only: true,
  formal_evidence: false,
  promotion_eligible: false,
  strategy_id: 'example_future_smoke_v1',
  strategy_name: 'Fixture strategy',
  strategy_entry_file: 'example_future_smoke_v1.py',
  strategy_sha256: 'a'.repeat(64),
  repository_commit: 'b'.repeat(40),
  bundle_path: '/configured/bundle',
  versions: { rqalpha: '2.0', rqsdk: '1.0', python: '3.13' },
  requested_config: serializeBacktestRunRequest(form),
  effective_config: {},
  effective_parameters: {
    order_book_id: 'IF1606',
    quantity: 2,
    risk_ratio: '0.0100',
    enabled: true,
  },
  status: 'running',
  started_at: '2026-08-23T01:02:03+00:00',
  finished_at: null,
  exit_code: null,
  failure_code: null,
}

describe('dedicated local backtest HTTP client', () => {
  it('defaults to the exact loopback sidecar URL and accepts the dedicated Vite override', () => {
    assert.equal(DEFAULT_BACKTEST_API_BASE_URL, 'http://127.0.0.1:8011/api/v1/backtests')
    assert.equal(resolveBacktestApiBaseUrl(undefined), DEFAULT_BACKTEST_API_BASE_URL)
    assert.equal(resolveBacktestApiBaseUrl('  '), DEFAULT_BACKTEST_API_BASE_URL)
    assert.equal(
      resolveBacktestApiBaseUrl('http://localhost:9011/custom/backtests///'),
      'http://localhost:9011/custom/backtests',
    )
  })

  it('serializes every financial field and declared decimal parameter as the original JSON string', () => {
    assert.deepEqual(serializeBacktestRunRequest(form), {
      strategy_id: 'example_future_smoke_v1',
      start_date: '2026-01-05',
      end_date: '2026-01-06',
      frequency: '1m',
      future_cash: '1000000.00',
      matching_type: 'next_bar',
      margin_multiplier: '1.00',
      futures_commission_multiplier: '1.00',
      slippage_model: 'PriceRatioSlippage',
      slippage: '0.0000',
      parameters: {
        order_book_id: 'IF1606',
        quantity: 2,
        risk_ratio: '0.0100',
        enabled: true,
      },
    })
  })

  it('posts the exact request through its own configured Axios instance', async () => {
    const requests: AxiosRequestConfig[] = []
    const adapter: AxiosAdapter = async (config) => {
      requests.push(config)
      return response(config, runningRun, 202)
    }
    const client = createBacktestClient({
      baseURL: 'http://localhost:9011/api/v1/backtests/',
      adapter,
    })

    const created = await client.startRun(form)

    assert.equal(created.run_id, RUN_ID)
    assert.equal(requests.length, 1)
    assert.equal(requests[0]?.baseURL, 'http://localhost:9011/api/v1/backtests')
    assert.equal(requests[0]?.url, '/runs')
    assert.equal(requests[0]?.method, 'post')
    assert.deepEqual(JSON.parse(String(requests[0]?.data)), serializeBacktestRunRequest(form))
  })

  it('uses only the six fixed routes and a bounded run-list limit', async () => {
    const requests: AxiosRequestConfig[] = []
    const health: BacktestHealth = {
      status: 'ready',
      research_only: true,
      formal_evidence: false,
      promotion_eligible: false,
      busy: false,
      runner: {
        available: true,
        rqalpha_version: '2.0',
        rqsdk_version: '1.0',
        python_version: '3.13',
      },
      bundle_available: true,
      runs_root_available: true,
      registry_available: true,
      error: null,
    }
    const adapter: AxiosAdapter = async (config) => {
      requests.push(config)
      const data = config.url === '/health'
        ? health
        : config.url === '/strategies'
          ? []
          : config.url === '/runs'
            ? []
            : { ...runningRun, result: null, stdout_tail: '', stderr_tail: '' }
      return response(config, data)
    }
    const client = createBacktestClient({ adapter })

    await client.health()
    await client.listStrategies()
    await client.listRuns(100)
    await client.getRun(RUN_ID)

    assert.deepEqual(
      requests.map(({ method, url, params }) => ({ method, url, params })),
      [
        { method: 'get', url: '/health', params: undefined },
        { method: 'get', url: '/strategies', params: undefined },
        { method: 'get', url: '/runs', params: { limit: 100 } },
        { method: 'get', url: `/runs/${RUN_ID}`, params: undefined },
      ],
    )
  })

  it('builds encoded allowlisted artifact URLs from the independent base URL', () => {
    assert.equal(
      artifactUrl(
        'http://127.0.0.1:8011/api/v1/backtests/',
        'run id/with slash',
        'report_zip',
      ),
      'http://127.0.0.1:8011/api/v1/backtests/runs/run%20id%2Fwith%20slash/artifacts/report_zip',
    )
    const client = createBacktestClient({ baseURL: 'http://localhost:9011/api/v1/backtests' })
    assert.equal(
      client.artifactUrl(RUN_ID, 'equity_png'),
      `http://localhost:9011/api/v1/backtests/runs/${RUN_ID}/artifacts/equity_png`,
    )
  })
})

describe('safe backtest error mapping', () => {
  it('maps an approved server code without exposing response detail or stack text', () => {
    const mapped = mapBacktestError({
      response: {
        data: {
          detail: {
            code: 'BACKTEST_ALREADY_RUNNING',
            message: 'secret /configured/bundle stack trace',
          },
        },
      },
      stack: 'license token secret',
    })

    assert.deepEqual(mapped, {
      code: 'BACKTEST_ALREADY_RUNNING',
      message: '已有回测正在运行，请等待完成后再试。',
    })
    assert.doesNotMatch(JSON.stringify(mapped), /secret|stack|license|configured/)
  })

  it('maps network and malformed failures to local-only setup guidance', () => {
    const mapped = mapBacktestError(new Error('connect ECONNREFUSED 127.0.0.1:8011'))

    assert.deepEqual(mapped, {
      code: 'BACKTEST_LOCAL_UNAVAILABLE',
      message: '本机回测服务不可用，请检查本机配置并重试。',
    })
    assert.doesNotMatch(mapped.message, /ECONNREFUSED|127\.0\.0\.1|8011/)
  })
})

function response<T>(
  config: AxiosRequestConfig,
  data: T,
  status = 200,
): AxiosResponse<T> {
  return {
    config: config as AxiosResponse<T>['config'],
    data,
    headers: {},
    status,
    statusText: status === 202 ? 'Accepted' : 'OK',
  }
}
