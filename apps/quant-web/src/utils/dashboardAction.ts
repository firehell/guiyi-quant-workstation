export type DashboardActionKind = 'runtime' | 'data' | 'live_signal' | 'review' | 'report' | 'jm_15m'

export interface DashboardActionRoute {
  name: string
  query?: Record<string, string>
}

export interface DashboardAction {
  kind: DashboardActionKind
  title: string
  detail: string
  to: DashboardActionRoute
}

export interface DashboardActionFacts {
  runtimeStatus?: string | null
  afterMarketStatus?: string | null
  dataStatus?: string | null
  latestLiveSignalEvent?: {
    event_id: number
    source_mode: string
    lifecycle_status: string
  } | null
  unfinishedReviewCount: number
  latestReportId?: number | null
}

const EXPLICIT_FAILURE = new Set(['failed', 'blocked'])

/** 研究工作站时间：无时区值保持原交易时间，显式时区统一显示为 Asia/Shanghai。 */
export function formatDashboardTimestamp(value?: string | null): string {
  if (!value) return '未提供'
  const naive = /^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})/.exec(value)
  const hasExplicitTimezone = /(?:Z|[+-]\d{2}:\d{2})$/i.test(value)
  if (naive && !hasExplicitTimezone) {
    return `${naive[1]}-${naive[2]}-${naive[3]} ${naive[4]}:${naive[5]}`
  }

  const date = new Date(value)
  if (!Number.isFinite(date.getTime())) return value
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Shanghai',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
  }).formatToParts(date)
  const field = (type: Intl.DateTimeFormatPartTypes) =>
    parts.find((part) => part.type === type)?.value || ''
  return `${field('year')}-${field('month')}-${field('day')} ${field('hour')}:${field('minute')}`
}

/** 只根据明确事实构建行动顺序；unknown 不提升为失败，historical replay 不提升为 live。 */
export function buildDashboardActions(facts: DashboardActionFacts): DashboardAction[] {
  const actions: DashboardAction[] = []
  if (EXPLICIT_FAILURE.has(facts.runtimeStatus ?? '') || EXPLICIT_FAILURE.has(facts.afterMarketStatus ?? '')) {
    actions.push({
      kind: 'runtime',
      title: '检查运行状态',
      detail: 'Runtime 或盘后归档明确失败；先查看只读诊断。',
      to: { name: 'runtime' },
    })
  }
  if (EXPLICIT_FAILURE.has(facts.dataStatus ?? '')) {
    actions.push({
      kind: 'data',
      title: '处理数据阻塞',
      detail: '数据质量明确 blocked/failed；研究入口保持 fail-closed。',
      to: { name: 'data' },
    })
  }
  const event = facts.latestLiveSignalEvent
  if (event?.source_mode === 'live_confirmed' && event.lifecycle_status === 'new') {
    actions.push({
      kind: 'live_signal',
      title: '查看新 Live SignalEvent',
      detail: `SignalEvent #${event.event_id} 仅供观察，不构成交易指令。`,
      to: { name: 'signal', query: { signal_event_id: String(event.event_id) } },
    })
  }
  if (facts.unfinishedReviewCount > 0) {
    actions.push({
      kind: 'review',
      title: `继续待复盘（${facts.unfinishedReviewCount}）`,
      detail: '完善已有 ReviewNote，不自动创建或写入复盘。',
      to: { name: 'review' },
    })
  } else if (facts.latestReportId) {
    actions.push({
      kind: 'report',
      title: `继续最近报告 #${facts.latestReportId}`,
      detail: '进入现有历史研究报告，不推断盈利或 live 能力。',
      to: { name: 'backtest', query: { report_id: String(facts.latestReportId) } },
    })
  }
  actions.push({
    kind: 'jm_15m',
    title: '打开 JM 15m 工作台',
    detail: '默认真实主力 · 历史浏览；Profile 与 quality 仍由 Market fail-closed。',
    to: {
      name: 'market-chart',
      query: {
        symbol: 'jm',
        period: '15m',
        contract_view: 'actual',
        data_mode: 'historical',
      },
    },
  })
  return actions
}
