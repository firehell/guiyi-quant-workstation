import { normalizeHomeCards, type HomeCard } from './newowHomeCards.ts'
export type ProjectionStatus = 'ready' | 'updating' | 'stale' | 'failed' | 'missing'
export interface HomeProjectionItem extends HomeCard {
  projection_status: ProjectionStatus
  period_status: Record<'1d' | '1w', ProjectionStatus>
  computed_at: string | null
  source_versions: Record<'1d' | '1w', string | null>
}
export interface HomeProjectionResponse {
  schema_version: 'newow_home_projection_v1'
  requested_at: string
  generated_at: string | null
  page_parity: true
  executable: false
  items: HomeProjectionItem[]
}
export function normalizeHomeProjection(raw: unknown): HomeProjectionResponse {
  const value = raw as HomeProjectionResponse
  if (value?.schema_version !== 'newow_home_projection_v1' || value.page_parity !== true || value.executable !== false || !Array.isArray(value.items) || value.items.length > 60) throw new Error('INVALID_HOME_PROJECTION')
  normalizeHomeCards({ schema_version: 'newow_home_cards_v2', requested_at: value.requested_at, items: value.items }, value.items.map(item => item.product))
  const states = ['ready', 'updating', 'stale', 'failed', 'missing']
  for (const item of value.items) {
    if (!/^[a-z]{1,4}$/.test(item.product) || !states.includes(item.projection_status) || !item.period_status || !item.source_versions || !['1d', '1w'].every(period => states.includes(item.period_status[period as '1d' | '1w']))) throw new Error('INVALID_HOME_PROJECTION')
    if (item.computed_at !== null && !Number.isFinite(Date.parse(item.computed_at))) throw new Error('INVALID_HOME_PROJECTION')
    for (const strategy of ['trend', 'oscillation'] as const) for (const period of ['1d', '1w'] as const) {
      if (item.strategies[strategy][period].snapshot_token) throw new Error('INVALID_HOME_PROJECTION')
    }
  }
  return value
}
