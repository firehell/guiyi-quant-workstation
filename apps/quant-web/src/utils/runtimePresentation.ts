import type { RuntimeHealthResponse } from '../api/runtime.ts'

export type RuntimeStatusTone = 'normal' | 'neutral' | 'warning' | 'danger'

export interface RuntimeStatusPresentationItem {
  key: 'overall' | 'live' | 'alert' | 'after_market' | 'weekly_audit'
  label: string
  state: string
  detail: string
  timestamp: string
  tone: RuntimeStatusTone
}

export function alertNotificationLabel(state: string): string {
  if (state === 'provider_accepted') return '服务商已接受（不代表送达）'
  if (state === 'failed') return '通知失败'
  return '未获自然验证'
}

export function afterMarketRunLabel(state: string): string {
  const labels: Record<string, string> = {
    disabled: '未启用',
    pending: '等待自然运行',
    running: '运行中',
    completed: '已完成',
    failed: '运行失败',
    missed: '未按时运行',
    stuck: '运行卡住',
    degraded: '状态异常',
  }
  return labels[state] ?? '状态未知'
}

export function formatRuntimeTimestamp(value: string | null): string {
  if (!value) return '时点不可用'
  const date = new Date(value)
  if (Number.isNaN(date.valueOf())) return '时点不可用'
  const parts = new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
  }).formatToParts(date)
  const part = (type: Intl.DateTimeFormatPartTypes) => parts.find((item) => item.type === type)?.value ?? ''
  return `${part('year')}-${part('month')}-${part('day')} ${part('hour')}:${part('minute')}`
}

export function runtimeStatusPresentation(snapshot: RuntimeHealthResponse): RuntimeStatusPresentationItem[] {
  const live = snapshot.components.live_market
  const alert = snapshot.components.alert
  const afterMarket = snapshot.components.after_market
  const alertDisabled = !alert.configured_enabled || alert.status === 'disabled'
  const processingState = alertDisabled
    ? '提醒未启用'
    : alert.processing_state === 'ok'
      ? '处理正常'
      : alert.processing_state === 'failed'
        ? '处理失败'
        : '未获自然验证'

  const items: RuntimeStatusPresentationItem[] = [
    {
      key: 'overall',
      label: '运行概况',
      state: overallLabel(snapshot.status),
      detail: '只读健康快照',
      timestamp: `生成 ${formatRuntimeTimestamp(snapshot.generated_at)}`,
      tone: statusTone(snapshot.status),
    },
    {
      key: 'live',
      label: '实时行情',
      state: liveLabel(live.status),
      detail: `${live.subscribed_count} / ${live.operational_count} 品种`,
      timestamp: live.last_bar_at
        ? `最近 K 线 ${formatRuntimeTimestamp(live.last_bar_at)}`
        : `心跳 ${formatRuntimeTimestamp(live.last_heartbeat_at)}`,
      tone: statusTone(live.status),
    },
    {
      key: 'alert',
      label: '提醒服务',
      state: processingState,
      detail: alertDisabled ? '运行观察已关闭' : alertNotificationLabel(alert.notification_state),
      timestamp: alert.last_processed_bar_at
        ? `最近处理 ${formatRuntimeTimestamp(alert.last_processed_bar_at)}`
        : `心跳 ${formatRuntimeTimestamp(alert.last_heartbeat_at)}`,
      tone: alertDisabled ? 'neutral' : statusTone(alert.status),
    },
    {
      key: 'after_market',
      label: '盘后维护',
      state: afterMarketRunLabel(afterMarket.run_state),
      detail: afterMarketDetail(afterMarket),
      timestamp: afterMarket.current_run
        ? afterMarket.current_run.updated_at
          ? `更新 ${formatRuntimeTimestamp(afterMarket.current_run.updated_at)}`
          : `开始 ${formatRuntimeTimestamp(afterMarket.current_run.started_at)}`
        : afterMarket.last_run
          ? `完成 ${formatRuntimeTimestamp(afterMarket.last_run.finished_at)}`
          : afterMarket.last_successful_trading_day
            ? `最近成功 ${afterMarket.last_successful_trading_day}`
            : '时点不可用',
      tone: statusTone(afterMarket.status),
    },
  ]
  const audit = snapshot.components.weekly_audit
  if (audit) {
    items.push({
      key: 'weekly_audit', label: '每周历史审计', state: weeklyAuditLabel(audit.status),
      detail: weeklyAuditDetail(audit),
      timestamp: `更新 ${formatRuntimeTimestamp(audit.updated_at)}`,
      tone: audit.status === 'passed' ? 'normal' : ['not_run', 'running', 'skipped_busy'].includes(audit.status) ? 'neutral' : 'warning',
    })
  }
  return items
}

export function weeklyAuditLabel(status: string): string {
  const labels: Record<string, string> = {
    not_run: '尚未审计', running: '审计中', passed: '审计通过', findings: '发现历史问题',
    failed: '审计失败', skipped_busy: '维护忙，已跳过', stuck: '审计卡住', stale: '审计已过期', invalid: '审计身份或状态无效',
  }
  return labels[status] ?? '状态未知'
}

export function weeklyAuditDetail(audit: NonNullable<RuntimeHealthResponse['components']['weekly_audit']>): string {
  return `operational 全历史 · 截至 ${audit.through ?? '未知'}${audit.finding_count == null ? '' : ` · ${audit.finding_count} 项发现`}`
}

export function afterMarketDetail(afterMarket: RuntimeHealthResponse['components']['after_market']): string {
  const current = afterMarket.current_run
  if (current?.stage) {
    const labels: Record<string, string> = {
      calendar: '交易日核对', rqdata_readiness: '数据就绪检查', planning: '制定更新范围',
      reading: '读取校验', provider: '获取数据', publishing: '发布', aggregation: '聚合',
      canonical_updated: '更新通知', live_reconciliation: '实时快照核对',
      live_cleanup: '当日实时清理', projection: '首页投影', retry_wait: '等待一次重试',
    }
    const counter = current.counters?.[current.stage]
    const partition = current.current_partition
    const operationCount = (phase: string, label: string) => {
      const count = current.counters?.[phase]
      return count ? `本次${label} ${count.completed} 次操作${count.total === undefined ? '' : ` / ${count.total} 次`}` : null
    }
    return [
      `第 ${current.attempt ?? 0} 次`, labels[current.stage] ?? '状态未知', current.current_symbol,
      partition ? `${partition.dataset[0]}/${partition.dataset[2]} · ${partition.dataset[3]} · ${partition.year}-${String(partition.month).padStart(2, '0')}` : null,
      typeof current.elapsed_seconds === 'number' && Number.isFinite(current.elapsed_seconds) && current.elapsed_seconds >= 0
        ? `累计 ${Number(current.elapsed_seconds.toPrecision(6))} 秒` : null,
      operationCount('reading', '读取校验'), operationCount('publishing', '已提交发布'),
      counter && !['reading', 'publishing'].includes(current.stage)
        ? `本次已完成 ${counter.completed} 次操作${counter.total === undefined ? '' : ` / ${counter.total} 次`}` : null,
      current.retry_at ? `重试 ${formatRuntimeTimestamp(current.retry_at)}` : null,
    ].filter(Boolean).join(' · ')
  }
  const notification = afterMarket.last_run?.failure_notification
  if (notification?.state === 'provider_accepted') {
    return '失败通知：服务商已接受（不代表送达）'
  }
  if (notification?.state === 'failed') return '失败通知：发送失败'
  return afterMarket.expected_trading_day
    ? `预期交易日 ${afterMarket.expected_trading_day}`
    : '预期交易日不可用'
}

function overallLabel(status: string): string {
  if (status === 'ok') return '整体正常'
  if (status === 'degraded') return '整体降级'
  if (status === 'failed') return '整体失败'
  return '整体未知'
}

function liveLabel(status: string): string {
  if (status === 'ok') return '实时正常'
  if (status === 'disabled') return '实时未启用'
  if (status === 'failed') return '实时异常'
  return '实时状态异常'
}

function statusTone(status: string): RuntimeStatusTone {
  if (status === 'ok') return 'normal'
  if (status === 'disabled' || status === 'pending' || status === 'unknown') return 'neutral'
  if (status === 'failed') return 'danger'
  return 'warning'
}
