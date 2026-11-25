import type { MonitorOverview, MonitorPage, MonitorRecord } from '../api/simulationMonitor.ts'
import type { SubingPortfolioStatus } from '../api/subingPortfolio.ts'

export type WorkstationAccountSource = 'htdy' | 'subing'

export interface WorkstationContractActivity {
  source: WorkstationAccountSource
  account: string
  product: string
  contract: string
  positions: string[]
  actions: { label: string; at: string | null }[]
  updatedAt: string | null
}

export function physicalContract(product: string, contract: string): string | null {
  const symbol = product.toUpperCase()
  const value = contract.toUpperCase()
  return /^[A-Z]{1,3}$/.test(symbol) && /^[A-Z]{1,3}\d{3,4}$/.test(value)
    && value.replace(/\d+$/, '') === symbol ? value : null
}

const positionLabel = (side: string, quantity: number) => {
  const direction = side === 'LONG' ? '多' : side === 'SHORT' ? '空' : '持仓'
  return `${direction} ${quantity} 手`
}

function latestTime(times: (string | null | undefined)[]): string | null {
  return times.filter((time): time is string => !!time && Number.isFinite(Date.parse(time)))
    .sort((a, b) => Date.parse(b) - Date.parse(a))[0] ?? null
}

const orderStates: Record<string, string> = {
  WORKING: '已受理', PARTIALLY_FILLED: '部分成交', CANCEL_PENDING: '撤单待确认',
  PROPOSED: '本地待提交', UNKNOWN: '委托结果待核验',
}

export function tqOrderActivity(order: MonitorRecord, records: readonly MonitorRecord[]): string | null {
  const status = orderStates[order.status]
  if (order.kind !== 'order' || !status) return null
  const fills = records.filter(fill => fill.kind === 'fill' && fill.status === 'RECORDED'
    && fill.order_id === order.order_id && fill.contract === order.contract)
  const total = fills.reduce((sum, fill) => sum + Number(fill.facts.quantity), 0)
  const orderQuantity = Number(order.facts.quantity)
  const partial = order.status === 'WORKING' && total > 0 && total < orderQuantity
  const effect = order.facts.offset === 'OPEN' ? '开仓' : order.facts.offset?.startsWith('CLOSE') ? '平仓' : '委托'
  return partial ? `${effect} · 部分成交（已读 ${total}/${orderQuantity} 手）` : `${effect} · ${status}`
}

export function projectTqAccount(overview: MonitorOverview | null, recordPage: MonitorPage | null) {
  const account = overview?.account
  const verified = overview?.position_projection_complete === true && overview.readback_status === 'verified'
  const rows = new Map<string, WorkstationContractActivity>()
  const records = recordPage?.coverage !== 'unavailable' ? recordPage?.items ?? [] : []
  function get(product: string, contract: string) {
    const physical = physicalContract(product, contract)
    if (!physical || !account) return null
    if (!rows.has(physical)) rows.set(physical, {
      source: 'htdy', account: account.alias, product: product.toLowerCase(), contract: physical,
      positions: [], actions: [], updatedAt: overview?.readback_at ?? null,
    })
    return rows.get(physical)!
  }
  for (const position of overview?.positions ?? []) {
    const row = get(position.product, position.contract)
    row?.positions.push(positionLabel(position.side, position.quantity))
    if (row) row.updatedAt = position.as_of
  }
  for (const order of records) {
    const label = tqOrderActivity(order, records)
    if (!label) continue
    const row = get(order.product, order.contract)
    if (!row) continue
    row.actions.push({ label: `快期执行记录 · ${label}`, at: order.at })
    row.updatedAt = latestTime([row.updatedAt, order.at])
  }
  for (const position of overview?.trading_scope?.status === 'FLATTEN_PENDING' ? overview.trading_scope.pending_positions : []) {
    const row = get(position.product, position.contract)
    row?.actions.push({ label: '范围退出义务', at: null })
  }
  return { verified, rows: [...rows.values()] }
}

const modelActionLabels: Record<string, string> = { OPEN: '待开仓', ADD: '待加仓', CLOSE: '待平仓', REDUCE: '待减仓' }
const readableModelStatus = new Set(['RUNNING', 'SESSION_BREAK', 'SESSION_COMPLETE', 'SESSION_CLOSED'])

export function projectSubingAccount(status: SubingPortfolioStatus | null) {
  const enabledProducts = status?.products.filter(product => product.enabled).map(product => product.product) ?? []
  const policyProducts = status?.account.policy?.products
  const completeScope = Array.isArray(policyProducts) && policyProducts.length > 0
    && enabledProducts.length === policyProducts.length && new Set(enabledProducts).size === policyProducts.length
    && policyProducts.every(product => enabledProducts.includes(product))
  const verified = !!status?.run_id && completeScope && readableModelStatus.has(status.status) && !!latestTime([status.observed_at])
  const rows: WorkstationContractActivity[] = []
  const exits = new Set(status?.account.pending_exit_contracts ?? [])
  for (const product of status?.run_id ? status.products : []) {
    for (const model of product.accounts) {
      const contract = physicalContract(product.product, model.contract)
      const quantity = model.summary?.open_quantity
      if (!contract || !(quantity > 0 || model.pending || exits.has(model.contract))) continue
      const actions: WorkstationContractActivity['actions'] = []
      if (model.pending) actions.push({
        label: `模型动作 · ${modelActionLabels[model.pending.kind] ?? model.pending.kind}`, at: model.pending.at,
      })
      if (exits.has(model.contract) && model.pending?.kind !== 'CLOSE') actions.push({ label: '模型待退出', at: null })
      rows.push({
        source: 'subing', account: '苏冰独立 Paper 模型账本', product: product.product.toLowerCase(), contract,
        positions: quantity > 0 ? [positionLabel(model.open_layers[0]?.side ?? '', quantity)] : [],
        actions, updatedAt: latestTime([model.valuation_at, model.pending?.at]),
      })
    }
  }
  return { verified, rows }
}
