import type { SubingThsAlertEvent } from '../types/market.ts'
import type { DetailViewModel, MarketDetailHeaderModel, MarketDetailIdentity } from '../types/marketDetail.ts'
import type { RuntimeAlertProjection } from './runtimeHealthTypes.ts'

export function buildSubingDetailViewModel(input: {
  identity: MarketDetailIdentity
  header: Pick<MarketDetailHeaderModel, 'displayContract' | 'asOf'>
  events: readonly SubingThsAlertEvent[]
  alertUnavailable: boolean
  rule: string | null
  ruleUnavailable: boolean
  runtime: RuntimeAlertProjection | null
  runtimeUnavailable: boolean
}): DetailViewModel {
  const latest = [...input.events].sort((left, right) => Date.parse(right.detected_at) - Date.parse(left.detected_at) || Date.parse(right.bar_end) - Date.parse(left.bar_end) || right.id - left.id)[0] ?? null
  const stale = input.alertUnavailable && !!latest
  const unavailable = input.alertUnavailable && !latest
  const signal = latest?.result_codes[0] === 'buy' ? 'S↑ 多头预警' : latest?.result_codes[0] === 'sell' ? 'S↓ 空头预警' : null
  const status = runtimeText(input.runtime, input.runtimeUnavailable)
  const history = [...input.events].sort((left, right) => Date.parse(right.detected_at) - Date.parse(left.detected_at)).map((event) => ({
    id: `subing-event:${event.id}`, label: event.result_codes[0] === 'buy' ? 'S↑ 多头预警' : 'S↓ 空头预警', occurredAt: event.detected_at,
    timeLabel: event.detected_at, source: 'alert_event' as const, barEnd: event.bar_end, contract: event.contract,
    markerType: event.result_codes[0] === 'buy' ? 'S↑' : 'S↓', formulaVersion: 'subing_ths_15m_v3', notificationAttemptedAt: event.notification_attempted_at,
  }))
  return {
    view: 'subing', identity: input.identity, asOf: latest?.detected_at ?? input.header.asOf,
    semanticBanner: { text: '正式 S↑ / S↓ 只来自 AlertEvent；图上的 EMA21 与 MACD 仅用于人工复核。', tone: 'info' },
    facts: [
      { id: 'latest-alert', label: '最新已保存预警', value: signal ? `${signal}${stale ? '（数据刷新失败，展示上一份成功快照）' : ''}` : unavailable ? '预警数据不可用' : '当前窗口暂无已保存苏冰预警', tone: signal ? (latest!.result_codes[0] === 'buy' ? 'up' : 'down') : unavailable ? 'unavailable' : 'default', source: 'alert_event' },
      { id: 'signal-kline', label: '信号 K 线', value: latest ? `${latest.bar_end} · ${latest.contract}` : unavailable ? '不可用' : '暂无', tone: latest ? 'default' : unavailable ? 'unavailable' : 'default', source: 'alert_event' },
      { id: 'alert-status', label: '预警状态', value: [input.ruleUnavailable ? 'Rule / Scope 不可用' : input.rule, status].filter(Boolean).join(' · '), tone: input.ruleUnavailable || input.runtimeUnavailable ? 'unavailable' : 'default', source: 'runtime' },
    ],
    disclosureSections: [
      { id: 'subing-latest', title: '最新已保存预警', summary: signal ?? (unavailable ? '预警数据不可用' : '当前窗口暂无已保存苏冰预警'), updatedAt: latest?.detected_at ?? null, tone: unavailable ? 'unavailable' : stale ? 'warning' : 'default', rows: latest ? [{ label: 'AlertEvent', value: `${signal} · ${latest.bar_end} · ${latest.contract}`, source: 'alert_event' }] : [] },
      { id: 'subing-formula', title: '触发口径', summary: 'subing_ths_15m_v3', updatedAt: null, tone: 'default', rows: [{ label: '固定展示身份', value: 'MACD(12,26,9) CROSS + EMA(CLOSE,21) · 仅供人工复核', source: 'generic_indicator' }] },
      { id: 'subing-runtime', title: '运行与通知', summary: status, updatedAt: input.runtime?.rule_status.subing_ths_alert_15m_v1.last_evaluated_bar_at ?? null, tone: input.runtimeUnavailable ? 'unavailable' : 'default', rows: runtimeRows(input.runtime) },
    ], history, dataStatus: unavailable ? 'unavailable' : stale ? 'stale' : 'ready',
  }
}

function runtimeText(runtime: RuntimeAlertProjection | null, unavailable: boolean): string {
  if (unavailable || !runtime) return 'Runtime 不可用'
  const rule = runtime.rule_status.subing_ths_alert_15m_v1
  if (rule.error_type === 'evaluation_warming_up') return '正在 warm-up'
  if (rule.error_type === 'evaluation_input_invalid') return '输入身份不可用'
  if (rule.error_type === 'evaluation_failed') return '评估失败'
  return rule.last_evaluated_bar_at ? '最近已评估' : '尚无已评估 Bar'
}

function runtimeRows(runtime: RuntimeAlertProjection | null) {
  if (!runtime) return [{ label: 'Runtime', value: '不可用', source: 'runtime' as const }]
  const rule = runtime.rule_status.subing_ths_alert_15m_v1
  return [
    { label: '全局状态', value: runtime.status, source: 'runtime' as const },
    { label: 'Rule 已评估 Bar', value: rule.last_evaluated_bar_at ?? '—', source: 'runtime' as const },
    { label: 'Rule 最近 Event', value: rule.last_event_at ?? '—', source: 'runtime' as const },
    { label: 'Rule 最近失败', value: rule.last_failure_at ?? '—', source: 'runtime' as const },
    { label: 'Rule 错误类型', value: rule.error_type ?? '—', source: 'runtime' as const },
    { label: '通知说明', value: '仅展示已保存 Event 与尝试时间；不表示外部送达。', source: 'runtime' as const },
  ]
}
