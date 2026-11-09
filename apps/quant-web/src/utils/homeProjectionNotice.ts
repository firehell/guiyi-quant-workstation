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
  const counts={ready:0,running:0,queued:0,failed:0,retry:0,dependency:0,unread:0}
  const blocked:string[]=[]
  for (const symbol of symbols) {
    const item=deliveries[symbol]
    if (!item) counts.unread++
    else if (item.projectionStatus==='ready') counts.ready++
    else if (item.recovery?.status==='running') counts.running++
    else if (item.recovery?.status==='blocked' || (item.projectionStatus==='failed' && item.recovery?.status!=='retry_wait' && item.recovery?.status!=='dependency_wait')) {
      counts.failed++; if (item.recovery?.status==='blocked') blocked.push(symbol.toUpperCase())
    }
    else if (item.recovery?.status==='retry_wait') counts.retry++
    else if (item.recovery?.status==='dependency_wait') counts.dependency++
    else counts.queued++
  }
  if (counts.ready===symbols.length) return ''
  const details=[['queued','排队'],['running','计算中'],['failed','失败'],['retry','重试等待'],['dependency','等待依赖'],['unread','待读取']] as const
  const label=entries.some(item=>Object.values(item?.periodReasons??{}).includes('SOURCE_VERSION_CHANGED')) ? '新版摘要正在重建' : '策略摘要正在更新'
  return `${label}，已完成${counts.ready}/${symbols.length}；${details.filter(([key])=>counts[key]).map(([key,text])=>`${text}${counts[key]}`).join('、')}${blocked.length ? `（阻塞：${blocked.join('、')}）` : ''}；展开品种可查看原因和截至时间。`
}
