import assert from 'node:assert/strict'
import { describe, it } from 'node:test'

import {
  BACKTEST_POLL_INTERVAL_MS,
  BacktestPoller,
  isLocalBacktestHostname,
  probeBacktestCapability,
  validateBacktestForm,
} from '../src/utils/backtestCapability.ts'
import type {
  BacktestHealth,
  BacktestRunDetail,
  BacktestRunForm,
  BacktestStrategy,
  RunStatus,
} from '../src/types/backtest.ts'


const RUN_ID = '20260823T010203000000Z-0123456789abcdef'

const strategy: BacktestStrategy = {
  id: 'example_future_smoke_v1',
  name: 'Fixture strategy',
  description: 'Test strategy',
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
    {
      name: 'order_book_id',
      type: 'enum',
      default: 'IF1606',
      minimum: null,
      maximum: null,
      options: ['IF1606'],
    },
    {
      name: 'quantity',
      type: 'integer',
      default: 1,
      minimum: 1,
      maximum: 10,
      options: [],
    },
    {
      name: 'risk_ratio',
      type: 'decimal',
      default: '0.01',
      minimum: '0',
      maximum: '1',
      options: [],
    },
    {
      name: 'enabled',
      type: 'boolean',
      default: true,
      minimum: null,
      maximum: null,
      options: [],
    },
  ],
  research_only: true,
  formal_evidence: false,
  promotion_eligible: false,
}

function validForm(changes: Partial<BacktestRunForm> = {}): BacktestRunForm {
  return {
    strategyId: strategy.id,
    startDate: '2026-01-05',
    endDate: '2026-01-06',
    frequency: '1d',
    futureCash: '1000000.00',
    matchingType: 'current_bar',
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
    ...changes,
  }
}

function health(changes: Partial<BacktestHealth> = {}): BacktestHealth {
  return {
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
    ...changes,
  }
}

describe('local-only browser capability', () => {
  it('accepts only localhost and 127.0.0.1 as local browser hostnames', () => {
    assert.equal(isLocalBacktestHostname('localhost'), true)
    assert.equal(isLocalBacktestHostname('LOCALHOST'), true)
    assert.equal(isLocalBacktestHostname('127.0.0.1'), true)
    assert.equal(isLocalBacktestHostname('192.168.1.20'), false)
    assert.equal(isLocalBacktestHostname('workstation.local'), false)
    assert.equal(isLocalBacktestHostname('::1'), false)
    assert.equal(isLocalBacktestHostname('localhost.example.com'), false)
  })

  it('makes zero probes and hides/refuses the capability on remote or LAN hosts', async () => {
    let probes = 0

    const capability = await probeBacktestCapability('192.168.1.20', async () => {
      probes += 1
      return health()
    })

    assert.equal(probes, 0)
    assert.deepEqual(capability, {
      kind: 'remote_blocked',
      showMenu: false,
      canStart: false,
      health: null,
      error: null,
    })
  })

  it('keeps the menu but refuses starts with safe retry guidance when local probing fails', async () => {
    const capability = await probeBacktestCapability('localhost', async () => {
      throw new Error('license path /secret')
    })

    assert.deepEqual(capability, {
      kind: 'local_unavailable',
      showMenu: true,
      canStart: false,
      health: null,
      error: {
        code: 'BACKTEST_LOCAL_UNAVAILABLE',
        message: '本机回测服务不可用，请检查本机配置并重试。',
      },
    })
  })

  it('allows starts only for a ready non-busy local sidecar', async () => {
    const ready = await probeBacktestCapability('127.0.0.1', async () => health())
    const busy = await probeBacktestCapability(
      '127.0.0.1',
      async () => health({ status: 'degraded', busy: true }),
    )
    const degraded = await probeBacktestCapability(
      '127.0.0.1',
      async () => health({ status: 'degraded', bundle_available: false }),
    )
    const inconsistentReady = await probeBacktestCapability(
      '127.0.0.1',
      async () => health({ bundle_available: false }),
    )

    assert.equal(ready.kind, 'ready')
    assert.equal(ready.showMenu, true)
    assert.equal(ready.canStart, true)
    assert.equal(busy.kind, 'ready')
    assert.equal(busy.showMenu, true)
    assert.equal(busy.canStart, false)
    assert.deepEqual(busy.error, {
      code: 'BACKTEST_ALREADY_RUNNING',
      message: '已有回测正在运行，请等待完成后再试。',
    })
    assert.equal(degraded.kind, 'local_unavailable')
    assert.equal(degraded.canStart, false)
    assert.equal(inconsistentReady.kind, 'local_unavailable')
    assert.equal(inconsistentReady.canStart, false)
  })
})

describe('pure backtest form validation', () => {
  it('enforces the exact frequency and matching matrix', () => {
    assert.deepEqual(validateBacktestForm(validForm(), strategy), {})
    assert.deepEqual(
      validateBacktestForm(
        validForm({ frequency: '1d', matchingType: 'next_bar' }),
        strategy,
      ),
      { matchingType: '1d 只支持 current_bar 撮合。' },
    )
    assert.deepEqual(
      validateBacktestForm(
        validForm({ frequency: '1m', matchingType: 'next_bar' }),
        strategy,
      ),
      {},
    )
  })

  it('rejects non-string, exponent, non-finite, spaced, and out-of-range decimals', () => {
    const malformed = [
      1000000,
      '1e6',
      'NaN',
      'Infinity',
      ' 1000000',
      '',
      '0',
      '-1',
    ]
    for (const futureCash of malformed) {
      const errors = validateBacktestForm(
        validForm({ futureCash: futureCash as string }),
        strategy,
      )
      assert.equal(errors.futureCash, '初始资金必须是大于 0 的十进制字符串。')
    }

    assert.equal(
      validateBacktestForm(validForm({ marginMultiplier: '0' }), strategy).marginMultiplier,
      '保证金倍数必须是大于 0 的十进制字符串。',
    )
    assert.equal(
      validateBacktestForm(
        validForm({ futuresCommissionMultiplier: '-0.01' }),
        strategy,
      ).futuresCommissionMultiplier,
      '手续费倍数必须是大于等于 0 的十进制字符串。',
    )
    assert.equal(
      validateBacktestForm(validForm({ slippage: '-0.01' }), strategy).slippage,
      '滑点必须是大于等于 0 的十进制字符串。',
    )
  })

  it('validates dates, strategy frequency, and all registered parameter kinds', () => {
    assert.deepEqual(
      validateBacktestForm(
        validForm({
          startDate: '2026-01-07',
          endDate: '2026-01-06',
          parameters: {
            order_book_id: 'UNREGISTERED',
            quantity: 11,
            risk_ratio: '1.01',
            enabled: 'true',
          },
        }),
        strategy,
      ),
      {
        dateRange: '开始日期不能晚于结束日期。',
        'parameters.order_book_id': '参数 order_book_id 必须选择注册选项。',
        'parameters.quantity': '参数 quantity 必须是 1 到 10 之间的整数。',
        'parameters.risk_ratio': '参数 risk_ratio 必须是 0 到 1 之间的十进制字符串。',
        'parameters.enabled': '参数 enabled 必须是布尔值。',
      },
    )
  })

  it('rejects an unsupported slippage model and parameters absent from the registry', () => {
    const errors = validateBacktestForm(
      validForm({
        slippageModel: 'CustomPythonSlippage' as BacktestRunForm['slippageModel'],
        parameters: {
          order_book_id: 'IF1606',
          quantity: 2,
          risk_ratio: '0.01',
          enabled: true,
          arbitrary_python: 'print(secret)',
        },
      }),
      strategy,
    )

    assert.deepEqual(errors, {
      slippageModel: '只支持注册的滑点模型。',
      'parameters.arbitrary_python': '参数 arbitrary_python 未在策略注册表中。',
    })
  })

  it('matches Python date ISO roundtrip rules from year 0001 through 9999', () => {
    const invalidDates = [
      '0000-01-01',
      '1900-02-29',
      '2026-02-29',
      '2026-04-31',
      '2026-13-01',
      '10000-01-01',
    ]
    for (const startDate of invalidDates) {
      assert.equal(
        validateBacktestForm(validForm({ startDate }), strategy).dateRange,
        '请输入有效的 ISO 日期。',
      )
    }

    assert.deepEqual(
      validateBacktestForm(validForm({ startDate: '0001-01-01', endDate: '9999-12-31' }), strategy),
      {},
    )
    assert.deepEqual(
      validateBacktestForm(validForm({ startDate: '2000-02-29', endDate: '2000-02-29' }), strategy),
      {},
    )
  })
})

describe('BacktestPoller lifecycle', () => {
  it('uses 2000ms and stops after a terminal status', async () => {
    const scheduler = new ManualScheduler()
    const updates: RunStatus[] = []
    const responses: RunStatus[] = ['running', 'succeeded']
    const poller = new BacktestPoller(
      async () => runDetail(responses.shift() ?? 'succeeded'),
      (run) => updates.push(run.status),
      { scheduler },
    )

    poller.start(RUN_ID)
    await flushPromises()

    assert.equal(BACKTEST_POLL_INTERVAL_MS, 2000)
    assert.deepEqual(updates, ['running'])
    assert.deepEqual(scheduler.delays(), [2000])

    scheduler.runNext()
    await flushPromises()

    assert.deepEqual(updates, ['running', 'succeeded'])
    assert.equal(scheduler.pendingCount, 0)
    assert.equal(poller.isPolling, false)
  })

  it('clears its timer and ignores an in-flight result after component disposal', async () => {
    const scheduler = new ManualScheduler()
    const deferred = new Deferred<BacktestRunDetail>()
    const updates: RunStatus[] = []
    const poller = new BacktestPoller(
      () => deferred.promise,
      (run) => updates.push(run.status),
      { scheduler },
    )

    poller.start(RUN_ID)
    poller.dispose()
    deferred.resolve(runDetail('running'))
    await flushPromises()

    assert.deepEqual(updates, [])
    assert.equal(scheduler.pendingCount, 0)
    assert.equal(poller.isPolling, false)
  })

  it('never overlaps requests and leaves no hanging timer after an exception', async () => {
    const scheduler = new ManualScheduler()
    const second = new Deferred<BacktestRunDetail>()
    let activeRequests = 0
    let maxActiveRequests = 0
    let calls = 0
    const errors: string[] = []
    const poller = new BacktestPoller(
      async () => {
        calls += 1
        activeRequests += 1
        maxActiveRequests = Math.max(maxActiveRequests, activeRequests)
        try {
          if (calls === 1) return runDetail('running')
          return await second.promise
        } finally {
          activeRequests -= 1
        }
      },
      () => undefined,
      {
        scheduler,
        onError: (error) => errors.push(error.code),
      },
    )

    poller.start(RUN_ID)
    await flushPromises()
    scheduler.runNext()
    await flushPromises()

    assert.equal(calls, 2)
    assert.equal(scheduler.pendingCount, 0)
    second.reject(new Error('network secret'))
    await flushPromises()

    assert.equal(maxActiveRequests, 1)
    assert.deepEqual(errors, ['BACKTEST_LOCAL_UNAVAILABLE'])
    assert.deepEqual(scheduler.delays(), [2000, 2000])

    poller.dispose()
    assert.equal(scheduler.pendingCount, 0)
  })

  it('does not let terminal run A stop run B started synchronously by the update callback', async () => {
    const scheduler = new ManualScheduler()
    const updates: string[] = []
    let poller: BacktestPoller
    poller = new BacktestPoller(
      async (runId) => runDetail(runId === 'run-a' ? 'succeeded' : 'running', runId),
      (run) => {
        updates.push(`${run.run_id}:${run.status}`)
        if (run.run_id === 'run-a') poller.start('run-b')
      },
      { scheduler },
    )

    poller.start('run-a')
    await flushPromises()

    assert.deepEqual(updates, ['run-a:succeeded', 'run-b:running'])
    assert.equal(poller.isPolling, true)
    assert.equal(scheduler.pendingCount, 1)
    assert.deepEqual(scheduler.delays(), [2000])

    poller.dispose()
  })
})

function runDetail(status: RunStatus, runId = RUN_ID): BacktestRunDetail {
  return {
    run_id: runId,
    research_only: true,
    formal_evidence: false,
    promotion_eligible: false,
    strategy_id: strategy.id,
    strategy_name: strategy.name,
    strategy_entry_file: 'example_future_smoke_v1.py',
    strategy_sha256: 'a'.repeat(64),
    repository_commit: 'b'.repeat(40),
    bundle_path: '/configured/bundle',
    versions: { rqalpha: '2.0', rqsdk: '1.0', python: '3.13' },
    requested_config: {
      strategy_id: strategy.id,
      start_date: '2026-01-05',
      end_date: '2026-01-06',
      frequency: '1d',
      future_cash: '1000000',
      matching_type: 'current_bar',
      margin_multiplier: '1',
      futures_commission_multiplier: '1',
      slippage_model: 'PriceRatioSlippage',
      slippage: '0',
      parameters: { order_book_id: 'IF1606', quantity: 1 },
    },
    effective_config: {},
    effective_parameters: { order_book_id: 'IF1606', quantity: 1 },
    status,
    started_at: '2026-08-23T01:02:03+00:00',
    finished_at: status === 'running' ? null : '2026-08-23T01:03:03+00:00',
    exit_code: status === 'succeeded' ? 0 : null,
    failure_code: null,
    result: null,
    stdout_tail: '',
    stderr_tail: '',
  }
}

class ManualScheduler {
  private nextId = 1
  private readonly timers = new Map<number, () => void>()
  private readonly scheduledDelays: number[] = []

  get pendingCount() {
    return this.timers.size
  }

  setTimeout = (callback: () => void, delay: number) => {
    const id = this.nextId
    this.nextId += 1
    this.timers.set(id, callback)
    this.scheduledDelays.push(delay)
    return id
  }

  clearTimeout = (id: number) => {
    this.timers.delete(id)
  }

  delays() {
    return [...this.scheduledDelays]
  }

  runNext() {
    const next = this.timers.entries().next().value as [number, () => void] | undefined
    assert.ok(next)
    this.timers.delete(next[0])
    next[1]()
  }
}

class Deferred<T> {
  readonly promise: Promise<T>
  private resolvePromise!: (value: T) => void
  private rejectPromise!: (reason: unknown) => void

  constructor() {
    this.promise = new Promise<T>((resolve, reject) => {
      this.resolvePromise = resolve
      this.rejectPromise = reject
    })
  }

  resolve(value: T) {
    this.resolvePromise(value)
  }

  reject(reason: unknown) {
    this.rejectPromise(reason)
  }
}

async function flushPromises() {
  await new Promise<void>((resolve) => setImmediate(resolve))
}
