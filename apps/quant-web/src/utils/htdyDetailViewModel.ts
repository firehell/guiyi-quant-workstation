import type { HtdyAlertEvent } from '../types/market.ts'
import type { DetailViewModel, MarketDetailHeaderModel, MarketDetailIdentity } from '../types/marketDetail.ts'
import { alertEventResultLabel } from './alertRules.ts'

export interface HtdyDetailViewModelInput {
  identity: MarketDetailIdentity
  header: MarketDetailHeaderModel
  rawObservation: '买观察' | '卖观察' | null
  rawUnavailable: boolean
  events: readonly HtdyAlertEvent[]
  alertUnavailable: boolean
  runtime: 'healthy' | 'degraded' | 'unavailable'
}

export function buildHtdyDetailViewModel(input: HtdyDetailViewModelInput): DetailViewModel {
  const persistentSupported = input.identity.seriesKind === 'actual_dominant'
  const newestEvents = [...input.events].sort((left, right) => Date.parse(right.detected_at) - Date.parse(left.detected_at))
  const latest = newestEvents[0]
  const dataStatus = input.header.freshness === 'fresh' ? 'ready' : input.header.freshness === 'stale' ? 'stale' : 'unavailable'
  const rawValue = input.rawUnavailable ? '当前观察不可用' : input.rawObservation ?? '暂无'
  const eventValue = !persistentSupported
    ? '持久首次识别 Event 仅属于真实主力序列'
    : input.alertUnavailable ? 'AlertEvent 暂不可用'
      : latest ? alertEventResultLabel(latest, latest.result_codes) : '暂无'
  return {
    view: 'htdy',
    identity: input.identity,
    asOf: input.header.asOf,
    semanticBanner: {
      text: '火天大有为含未来函数的回画观察，仅供研究复核；不可用于严格回测或交易。当前观察可重绘，首次识别 Event 为独立持久事实。',
      tone: 'warning',
    },
    facts: [
      fact('current-observation', '当前重绘观察', rawValue, 'htdy_display', input.rawUnavailable ? 'unavailable' : input.rawObservation ? 'warning' : 'default'),
      fact('first-seen-event', '首次识别 Event', eventValue, 'alert_event', !persistentSupported || input.alertUnavailable ? 'unavailable' : latest ? directionalTone(latest) : 'default'),
      fact('alert-runtime', '预警运行状态', runtimeText(input.runtime), 'runtime', input.runtime === 'healthy' ? 'default' : input.runtime === 'degraded' ? 'warning' : 'unavailable'),
    ],
    disclosureSections: [
      {
        id: 'htdy-observation', title: '观察与 Event 口径', summary: '当前回画观察与持久首次识别 Event 分别展示，不能相互替代。', updatedAt: input.header.asOf, tone: 'warning',
        rows: [
          { label: '当前观察', value: '由既有 HTDY 展示内核计算，允许回画，不创建 Event。', source: 'htdy_display' },
          { label: '首次识别 Event', value: persistentSupported ? '仅真实主力序列的 HTDY AlertEvent；按首次识别时间冻结。' : '当前序列没有持久首次识别 Event 权威。', source: 'alert_event' },
          { label: '预警状态', value: runtimeText(input.runtime), source: 'runtime' },
        ],
      },
      ...input.header.extendedSections,
    ],
    history: persistentSupported && !input.alertUnavailable ? newestEvents.map((event) => ({
      id: `htdy-event:${event.id}`,
      label: `${alertEventResultLabel(event, event.result_codes)} · 首次识别 · ${event.contract}${event.notification_attempted_at ? ' · 已尝试通知' : ''}`,
      occurredAt: event.detected_at,
      source: 'alert_event' as const,
    })) : [],
    dataStatus,
  }
}

function fact(
  id: string, label: string, value: string,
  source: 'htdy_display' | 'alert_event' | 'runtime',
  tone: 'default' | 'up' | 'down' | 'warning' | 'unavailable',
) {
  return { id, label, value, source, tone } as const
}

function directionalTone(event: HtdyAlertEvent): 'up' | 'down' | 'warning' {
  return event.result_codes.includes('buy') ? 'up' : event.result_codes.includes('sell') ? 'down' : 'warning'
}

function runtimeText(value: HtdyDetailViewModelInput['runtime']): string {
  return value === 'healthy' ? '运行正常' : value === 'degraded' ? '运行降级' : '运行状态不可用'
}
