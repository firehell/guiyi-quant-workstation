import type { CardDelivery } from './newowHomeCards.ts'
import type { HomeReadFailure } from './homeProjectionReadLoop.ts'
import { formatBeijingInstant } from './marketDisplay.ts'

export function homeRecoveryNotice(delivery?: CardDelivery): string {
  if (!delivery) return '暂无已验证摘要'
  const recovery = delivery.recovery
  const cutoff = (period: '1d' | '1w') => { const value = delivery.card?.strategies.trend[period].bar_end; return value ? formatBeijingInstant(value) : '待确认' }
  const history = delivery.card ? `暂用日线截至 ${cutoff('1d')}、周线截至 ${cutoff('1w')} 的历史摘要` : '暂无已验证摘要'
  if (recovery?.status === 'blocked') return `更新阻塞（${recovery.category ?? '原因待确认'}${recovery.code ? ` / ${recovery.code}` : ''}）；${history}${recovery.last_attempt_at ? `；最近尝试 ${formatBeijingInstant(recovery.last_attempt_at)}` : ''}`
  if (delivery.projectionStatus === 'ready') return ''
  const label = recovery?.status === 'running' ? '计算中' : recovery?.status === 'retry_wait' ? '重试等待' : recovery?.status === 'dependency_wait' ? '等待依赖恢复' : delivery.projectionStatus === 'failed' ? '摘要更新失败，等待恢复状态' : '待更新'
  return `${label}；${history}${recovery?.next_attempt_at ? `；最早重试 ${formatBeijingInstant(recovery.next_attempt_at)}` : ''}`
}

export function homeProjectionSummary(symbols: readonly string[], deliveries: Record<string, CardDelivery>, failure: HomeReadFailure | null): string {
  const entries = symbols.map(symbol => deliveries[symbol])
  const history = entries.some(value => value?.card) ? '保留已验证的历史摘要' : '暂无已验证摘要'
  if (failure === 'access') return `策略摘要访问受限，请恢复访问权限；${history}。`
  if (failure === 'protocol') return `策略摘要响应校验失败，将低频重新读取；${history}。`
  if (failure === 'transport') return `策略摘要读取失败，正在自动重试；${history}。`
  const blocked = symbols.filter(symbol => deliveries[symbol]?.recovery?.status === 'blocked')
  if (blocked.length) return `当前板块 ${blocked.length} 个品种更新阻塞：${blocked.map(symbol => symbol.toUpperCase()).join('、')}；展开可查看原因及最近尝试时间。`
  const updating = entries.filter(value => value?.projectionStatus !== 'ready')
  if (updating.length) return `当前板块 ${updating.length} 个品种待更新或恢复中；展开可查看状态、原因和截至时间。`
  return ''
}
