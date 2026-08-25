import type { RuntimeHealthResponse } from '../api/runtime.ts'

export type RuntimeStatusTone = 'normal' | 'neutral' | 'warning' | 'danger'

export interface RuntimeStatusPresentationItem {
  key: 'overall' | 'live' | 'alert' | 'after_market'
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

  return [
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
        ? `开始 ${formatRuntimeTimestamp(afterMarket.current_run.started_at)}`
        : afterMarket.last_run
          ? `完成 ${formatRuntimeTimestamp(afterMarket.last_run.finished_at)}`
          : afterMarket.last_successful_trading_day
            ? `最近成功 ${afterMarket.last_successful_trading_day}`
            : '时点不可用',
      tone: statusTone(afterMarket.status),
    },
  ]
}

function afterMarketDetail(afterMarket: RuntimeHealthResponse['components']['after_market']): string {
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
