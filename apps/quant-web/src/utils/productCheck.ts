import type { EventState } from '../types/executionReview.ts'
import type { AlertEvent, ProductResearchResponse } from '../types/market.ts'
import { alertResultLabel, alertRuleShortLabel } from './alertRules.ts'
import { executionReviewActionLabel } from './executionReview.ts'

export interface MarketBackgroundSummary {
  label: '同向偏多' | '同向偏空' | '中性' | '未共振' | '数据不足'
  tone: 'up' | 'down' | 'neutral' | 'warning'
}

export function summarizeMarketBackground(
  daily: ProductResearchResponse['daily_trend'],
  weekly: ProductResearchResponse['weekly_trend'],
): MarketBackgroundSummary {
  if (daily === 'unavailable' || weekly === 'unavailable') {
    return { label: '数据不足', tone: 'warning' }
  }
  if (daily === 'up' && weekly === 'up') return { label: '同向偏多', tone: 'up' }
  if (daily === 'down' && weekly === 'down') return { label: '同向偏空', tone: 'down' }
  if (daily === 'neutral' && weekly === 'neutral') return { label: '中性', tone: 'neutral' }
  return { label: '未共振', tone: 'warning' }
}

export interface FormalEventSummary {
  event: AlertEvent
  state: EventState | null
  headline: string
  actionLabel: string | null
}

export function summarizeFormalEvent(
  items: AlertEvent[],
  states: Record<number, EventState>,
): FormalEventSummary | null {
  const event = [...items].sort((left, right) => Date.parse(right.bar_end) - Date.parse(left.bar_end))[0]
  if (!event) return null
  const state = states[event.id] ?? null
  return {
    event,
    state,
    headline: `${alertRuleShortLabel(event.rule_code)} · ${alertResultLabel(event.rule_code, event.result_codes)}`,
    actionLabel: state ? executionReviewActionLabel(state.state) : null,
  }
}
