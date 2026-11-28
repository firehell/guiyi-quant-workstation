import type { RuntimeHealthResponse } from '../api/runtime.ts'

const labels: Record<string, string> = {
  ok: '正常', pending: '等待', disabled: '已停用', failed: '失败', degraded: '降级',
  unverified: '待核验', unknown: '未知', not_due: '未到期', lagging: '滞后', stale: '已过期',
  passed: '通过', findings: '有质量问题', missed: '错过执行', stuck: '停滞', not_run: '尚未运行',
  running: '运行中', idle: '空闲', matched: '身份一致', invalid: '身份异常', skipped_busy: '资源占用已跳过',
}
export function healthLabel(status?: string | null) {
  return status ? labels[status] ?? status : '暂无读回'
}
const components = [
  ['db', 'PostgreSQL Catalog'], ['redis', 'Redis'], ['live_market', '盘中行情'],
  ['after_market', '盘后归档'], ['alert', '预警'], ['weekly_audit', '历史质量审计'],
  ['reference_worker', '策略参考计算'], ['late_provider_recovery', '延迟行情恢复'],
] as const

export function componentRows(health?: RuntimeHealthResponse) {
  if (!health) return []
  return components.filter(([key]) => key in health.components || !['late_provider_recovery', 'reference_worker', 'weekly_audit'].includes(key)).map(([key, title]) => {
    const fact = health.components[key]
    return { key, title, status: fact?.status, diagnostic: fact && 'error_type' in fact ? fact.error_type : null }
  })
}

export function needsAttention(status?: string) {
  return !status || ['failed', 'degraded', 'unknown', 'unverified', 'stale', 'lagging', 'findings', 'missed', 'stuck', 'invalid'].includes(status)
}
