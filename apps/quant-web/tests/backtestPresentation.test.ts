import assert from 'node:assert/strict'
import { describe, it } from 'node:test'

import {
  backtestRunStatusLabel,
  backtestRunStatusTagType,
  formatBacktestDuration,
  visibleBacktestArtifacts,
} from '../src/utils/backtestPresentation.ts'
import type { BacktestRunDetail, RunStatus } from '../src/types/backtest.ts'


function run(status: RunStatus, result: BacktestRunDetail['result'] = null): BacktestRunDetail {
  return {
    run_id: 'run-1',
    research_only: true,
    formal_evidence: false,
    promotion_eligible: false,
    strategy_id: 'fixture',
    strategy_name: 'Fixture',
    strategy_entry_file: 'fixture.py',
    strategy_sha256: 'a'.repeat(64),
    repository_commit: 'b'.repeat(40),
    bundle_path: '/configured/bundle',
    versions: { rqalpha: '2.0', rqsdk: '1.0', python: '3.13' },
    requested_config: {
      strategy_id: 'fixture', start_date: '2026-01-01', end_date: '2026-01-02',
      frequency: '1d', future_cash: null, matching_type: null, margin_multiplier: null,
      futures_commission_multiplier: null, slippage_model: null, slippage: null, parameters: {},
    },
    effective_config: {},
    effective_parameters: {},
    status,
    started_at: '2026-08-23T01:00:00Z',
    finished_at: status === 'running' ? null : '2026-08-23T01:01:07Z',
    exit_code: status === 'succeeded' ? 0 : 2,
    failure_code: status === 'succeeded' ? null : 'RUNNER_EXITED',
    result,
    stdout_tail: '',
    stderr_tail: '',
  }
}

describe('shared backtest presentation', () => {
  it('provides one shared label and tag type for every run status', () => {
    assert.deepEqual(
      (['running', 'succeeded', 'failed', 'timed_out', 'interrupted'] as const).map((status) => [
        backtestRunStatusLabel(status),
        backtestRunStatusTagType(status),
      ]),
      [
        ['运行中', 'info'],
        ['已成功', 'success'],
        ['失败', 'error'],
        ['已超时', 'error'],
        ['已中断', 'error'],
      ],
    )
  })

  it('shows an in-progress duration while running and elapsed time after completion', () => {
    assert.equal(formatBacktestDuration(run('running')), '进行中')
    assert.equal(formatBacktestDuration(run('succeeded')), '1 分 7 秒')
    assert.equal(formatBacktestDuration({ ...run('failed'), started_at: 'invalid' }), '—')
  })

  it('always exposes fixed logs for terminal failures without a result', () => {
    for (const status of ['failed', 'timed_out', 'interrupted'] as const) {
      assert.deepEqual(visibleBacktestArtifacts(run(status)), ['stdout_log', 'stderr_log'])
    }
    assert.deepEqual(visibleBacktestArtifacts(run('running')), [])
  })

  it('uses result availability for succeeded artifacts', () => {
    const succeeded = run('succeeded', {
      summary: {
        total_returns: '0', annualized_returns: '0', max_drawdown: '0', sharpe: '0',
        sortino: '0', volatility: '0', total_value: '1', cash: '1',
      },
      equity: [],
      trade_count: '0',
      artifacts: {
        report_zip: true,
        result_pickle: false,
        equity_png: true,
        stdout_log: true,
        stderr_log: false,
        run_json: true,
      },
    })

    assert.deepEqual(
      visibleBacktestArtifacts(succeeded),
      ['report_zip', 'equity_png', 'stdout_log', 'run_json'],
    )
  })
})
