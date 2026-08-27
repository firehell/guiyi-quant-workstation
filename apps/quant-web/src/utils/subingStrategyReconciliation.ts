import type {
  AlertEvent,
  KlineMarker,
  SubingStrategyAction,
  SubingStrategyActionPayloadWire,
  SubingStrategyEpisode,
} from '../types/market.ts'
import { subingStrategyActionToMarker } from './historicalResearchMarkers.ts'
import { isSubingStrategyAlertEvent, strategyActionLabel } from './alertRules.ts'

export const STRATEGY_ACTION_FACT_MISMATCH = 'STRATEGY_ACTION_FACT_MISMATCH' as const

export interface SubingStrategyReconciliationResult {
  markers: KlineMarker[]
  mismatchActionIds: string[]
  errorCodes: Array<typeof STRATEGY_ACTION_FACT_MISMATCH>
}

export function reconcileSubingStrategyActions(
  historicalActions: readonly SubingStrategyAction[],
  historicalEpisodes: readonly SubingStrategyEpisode[],
  liveEvents: readonly AlertEvent[],
): SubingStrategyReconciliationResult {
  const episodes = new Map(historicalEpisodes.map((episode) => [episode.episode_id, episode]))
  const historical = new Map(historicalActions.map((action) => [action.action_id, action]))
  const markers = new Map<string, KlineMarker>()
  const mismatchActionIds: string[] = []

  for (const action of historicalActions) {
    markers.set(action.action_id, subingStrategyActionToMarker(action, episodes))
  }
  for (const event of liveEvents) {
    if (
      !isSubingStrategyAlertEvent(event)
      || event.action_id === null
      || event.strategy_action === null
      || event.action_id !== event.strategy_action.action_id
    ) continue
    const canonical = historical.get(event.action_id)
    if (!canonical) {
      markers.set(event.action_id, liveEventMarker(event))
      continue
    }
    if (!sameActionFacts(canonical, episodes.get(canonical.episode_id), event.strategy_action)) {
      mismatchActionIds.push(event.action_id)
    }
  }

  const uniqueMismatches = [...new Set(mismatchActionIds)].sort()
  return {
    markers: [...markers.values()].sort((left, right) => (
      Date.parse(left.time) - Date.parse(right.time) || left.id.localeCompare(right.id)
    )),
    mismatchActionIds: uniqueMismatches,
    errorCodes: uniqueMismatches.length ? [STRATEGY_ACTION_FACT_MISMATCH] : [],
  }
}

function liveEventMarker(event: AlertEvent): KlineMarker {
  const action = event.strategy_action!
  const long = action.kind.endsWith('_long')
  const open = action.kind.startsWith('open_')
  const label = strategyActionLabel(action.kind)
  return {
    id: `strategy-event:${action.action_id}`,
    dedupeKey: action.action_id,
    time: action.effective_bar_end,
    label,
    tooltip: `苏冰策略事件 · ${action.contract} · ${label} · 参考价 ${action.reference_price}`,
    tone: long ? 'up' : 'down',
    position: open ? (long ? 'belowBar' : 'aboveBar') : (long ? 'aboveBar' : 'belowBar'),
    shape: open ? (long ? 'arrowUp' : 'arrowDown') : 'square',
  }
}

function sameActionFacts(
  action: SubingStrategyAction,
  episode: SubingStrategyEpisode | undefined,
  payload: SubingStrategyActionPayloadWire,
): boolean {
  const open = action.kind.startsWith('open_')
  const expected = {
    schema_version: 1,
    ...wireActionFacts(action),
    entry: open || !episode ? null : {
      action_id: episode.entry_action.action_id,
      kind: episode.entry_action.kind,
      effective_bar_end: instant(episode.entry_action.effective_bar_end),
      reference_price: decimal(episode.entry_action.reference_price),
      confirmation_source: episode.entry_action.confirmation_source,
    },
    holding_bar_count: open || !episode ? null : episode.holding_bar_count,
    reference_change_percent: open || !episode || episode.reference_change_percent === null
      ? null : decimal(episode.reference_change_percent),
  }
  const actual = {
    ...payload,
    decision_at: instant(payload.decision_at),
    effective_open_at: nullableInstant(payload.effective_open_at),
    effective_bar_end: instant(payload.effective_bar_end),
    reference_price: decimal(payload.reference_price),
    bound_reference_pivot: payload.bound_reference_pivot === null ? null : {
      ...payload.bound_reference_pivot,
      pivot_time: instant(payload.bound_reference_pivot.pivot_time),
      confirmed_at: instant(payload.bound_reference_pivot.confirmed_at),
      price: decimal(payload.bound_reference_pivot.price),
    },
    entry: payload.entry === null ? null : {
      ...payload.entry,
      effective_bar_end: instant(payload.entry.effective_bar_end),
      reference_price: decimal(payload.entry.reference_price),
    },
    reference_change_percent: payload.reference_change_percent === null
      ? null : decimal(payload.reference_change_percent),
  }
  return JSON.stringify(canonicalJson(expected)) === JSON.stringify(canonicalJson(actual))
}

function wireActionFacts(action: SubingStrategyAction) {
  return {
    action_id: action.action_id,
    episode_id: action.episode_id,
    strategy_id: action.strategy_id,
    formula_version: action.formula_version,
    kind: action.kind,
    symbol: action.symbol,
    contract: action.contract,
    trading_day: action.trading_day,
    segment_start_trading_day: action.segment_start_trading_day,
    opportunity_id: action.opportunity_id,
    decision_at: instant(action.decision_at),
    effective_open_at: nullableInstant(action.effective_open_at),
    effective_bar_end: instant(action.effective_bar_end),
    reference_price: decimal(action.reference_price),
    fill_basis: action.fill_basis,
    confirmation_source: action.confirmation_source,
    reason_codes: action.reason_codes,
    direction_context_source_day: action.direction_context_source_day,
    direction_context_target_day: action.direction_context_target_day,
    bound_reference_pivot: action.bound_reference_pivot === null ? null : {
      ...action.bound_reference_pivot,
      pivot_time: instant(action.bound_reference_pivot.pivot_time),
      confirmed_at: instant(action.bound_reference_pivot.confirmed_at),
      price: decimal(action.bound_reference_pivot.price),
    },
  }
}

function decimal(value: string): string {
  const text = String(value).trim()
  const match = /^(-?)(\d+)(?:\.(\d*))?$/.exec(text)
  if (!match) return text
  const integer = match[2].replace(/^0+(?=\d)/, '')
  const fraction = (match[3] ?? '').replace(/0+$/, '')
  const nonZero = integer !== '0' || fraction.length > 0
  return `${match[1] && nonZero ? '-' : ''}${integer}${fraction ? `.${fraction}` : ''}`
}

function instant(value: string): string {
  const parsed = Date.parse(value)
  return Number.isFinite(parsed) ? new Date(parsed).toISOString() : value
}

function nullableInstant(value: string | null): string | null {
  return value === null ? null : instant(value)
}

function canonicalJson(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(canonicalJson)
  if (typeof value !== 'object' || value === null) return value
  return Object.fromEntries(
    Object.entries(value)
      .sort(([left], [right]) => left.localeCompare(right))
      .map(([key, item]) => [key, canonicalJson(item)]),
  )
}
