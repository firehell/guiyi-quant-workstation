import assert from 'node:assert/strict'
import test from 'node:test'
import type { MonitorOverview, MonitorPage, MonitorRecord } from '../src/api/simulationMonitor.ts'
import type { SubingPortfolioStatus } from '../src/api/subingPortfolio.ts'
import { projectSubingAccount, projectTqAccount } from '../src/utils/workstationAccounts.ts'
import { activityChartLink } from '../src/utils/workstationRoutes.ts'
import { locateChartExecutions, tqChartExecutions } from '../src/utils/workstationChartActivity.ts'

const earlier = '2026-11-25T10:00:00+08:00'
const later = '2026-11-25T10:30:00+08:00'
const model: SubingPortfolioStatus = {
  run_id: 'pinned-run', status: 'RUNNING', observed_at: later, trading_day: '2026-11-25', auto_order: false,
  account: { policy: { products: ['jm'] }, pending_exit_contracts: ['JM2701'] },
  products: [{ product: 'jm', enabled: true, accounts: [
    { contract: 'JM2701', valuation_at: later, summary: { open_quantity: 1 }, open_layers: [{ side: 'LONG' }], fills: [], pending: { kind: 'CLOSE', at: earlier } },
    { contract: 'JM2705', valuation_at: earlier, summary: { open_quantity: 0 }, open_layers: [], fills: [], pending: { kind: 'OPEN', at: later } },
  ] }],
}

test('model uses the physical old contract and keeps empty plus pending open independent', () => {
  const state = projectSubingAccount(model)
  assert.equal(state.verified, true)
  assert.deepEqual(state.rows.map(row => [row.contract, row.positions, row.actions, row.updatedAt]), [
    ['JM2701', ['多 1 手'], [{ label: '模型动作 · 待平仓', at: earlier }], later],
    ['JM2705', [], [{ label: '模型动作 · 待开仓', at: later }], later],
  ])
  assert.equal(state.rows[0]?.account, '苏冰独立 Paper 模型账本')
  const link = activityChartLink(state.rows[0]!)
  assert.equal(link.query.contract, 'JM2701')
  assert.equal(link.query.view, 'subing')
  assert.equal(link.query.series_kind, 'contract')
})

test('a stale model stays a historical snapshot and a missing run gives no account projection', () => {
  const stale = projectSubingAccount({ ...model, status: 'STALE_OR_STOPPED' })
  assert.equal(stale.verified, false)
  assert.equal(stale.rows.length, 2)
  assert.deepEqual(projectSubingAccount({ ...model, run_id: null }), { verified: false, rows: [] })
})

const order: MonitorRecord = {
  id: 'order:1', kind: 'order', at: earlier, product: 'JM', contract: 'JM2701', status: 'WORKING',
  label: '已受理', order_id: '1', signal_id: null, facts: { offset: 'CLOSE', quantity: '3' },
}
const fill: MonitorRecord = {
  ...order, id: 'fill:1', kind: 'fill', status: 'RECORDED', at: later,
  facts: { quantity: '1', filled_at: '2026-11-25T10:15:00.123456+08:00', price: '804.5', native_precision_seconds: '0.000001' },
}

test('positive partial-fill proof is retained without treating the recent page as an account snapshot', () => {
  const monitor = {
    account: { alias: '快期模拟主账户' }, position_projection_complete: false,
    readback_status: 'stale', readback_at: later, positions: [],
  } as unknown as MonitorOverview
  const page = { coverage: 'complete', items: [order, fill], next_cursor: 'more' } as MonitorPage
  const result = projectTqAccount(monitor, page)
  assert.equal(result.verified, false)
  assert.equal(result.rows[0]?.account, '快期模拟主账户')
  assert.deepEqual(result.rows[0]?.actions, [{ label: '快期执行记录 · 平仓 · 部分成交（已读 1/3 手）', at: earlier }])
  assert.equal(result.rows[0]?.updatedAt, later)
  assert.deepEqual(projectTqAccount(monitor, null), { verified: false, rows: [] })
})

test('original fill time and price can be plotted between compatible bars, without inventing gap coordinates', () => {
  const events = tqChartExecutions([order, fill], '快期模拟主账户')
  assert.equal(events.length, 1)
  const base = { time: earlier, trading_day: '2026-11-25', physicalContract: 'JM2701',
    calculationSegmentId: 'segment', open: 800, high: 810, low: 799, close: 800, volume: 100 }
  const next = { ...base, time: later }
  const marks = locateChartExecutions(events, [base, next], '30m')
  assert.equal(marks[0]?.time, fill.facts.filled_at)
  assert.equal(marks[0]?.price, '804.5')
  assert.ok(marks[0]?.ratio && marks[0].ratio > 0.5)
  assert.equal(locateChartExecutions(events, [base, next], '15m').length, 0)
  assert.equal(locateChartExecutions(events, [base, { ...next, physicalContract: 'JM2705' }], '30m').length, 0)
})

test('native manual order coordinates require recorded original price, time and reconciliation evidence', () => {
  const manual = { ...order, status: 'FILLED', facts: {
    execution_origin: 'OWNER_MANUAL_CLOSE', evidence_sha256: 'a'.repeat(64), price: '805',
  } }
  assert.deepEqual(tqChartExecutions([order, manual], '快期模拟主账户'), [{
    id: manual.id, source: '快期原生委托', account: '快期模拟主账户', contract: 'JM2701', time: earlier, price: '805',
  }])
  assert.deepEqual(tqChartExecutions([{ ...manual, facts: { ...manual.facts, evidence_sha256: null } }], '快期模拟主账户'), [])
})
