import type { AlertEvent, MarketFrequency, SeriesKind } from './market.ts'
import type { MarketDetailIconName } from '../utils/marketDetailIcons.ts'

export const MARKET_DETAIL_VIEWS = ['trend', 'htdy', 'subing', 'free'] as const
export type MarketDetailView = (typeof MARKET_DETAIL_VIEWS)[number]

export interface FlexibleViewRestore {
  seriesKind: Extract<SeriesKind, 'actual_dominant' | 'continuous'>
  frequency: MarketFrequency
}

export interface MarketDetailViewRestore {
  htdy: FlexibleViewRestore
  free: FlexibleViewRestore
}

export interface MarketDetailIdentity {
  view: MarketDetailView
  symbol: string
  seriesKind: SeriesKind
  contract?: string
  frequency: MarketFrequency
  focusBarEnd?: string
}

export type MarketDetailRouteErrorCode =
  | 'DETAIL_VIEW_UNKNOWN'
  | 'DETAIL_SYMBOL_INVALID'
  | 'DETAIL_TREND_IDENTITY_INVALID'
  | 'DETAIL_SUBING_IDENTITY_INVALID'
  | 'DETAIL_SERIES_KIND_INVALID'
  | 'DETAIL_FREQUENCY_INVALID'
  | 'DETAIL_CONTRACT_REQUIRED'
  | 'DETAIL_FOCUS_INVALID'

export type MarketDetailRouteResult =
  | { kind: 'missing-view'; symbol: string | null }
  | { kind: 'invalid'; code: MarketDetailRouteErrorCode; recovery: MarketDetailIdentity | null }
  | { kind: 'valid'; identity: MarketDetailIdentity }

export type MarketDetailAlertEvent = AlertEvent

export type MarketDetailSource =
  | 'market'
  | 'newow'
  | 'htdy_display'
  | 'alert_event'
  | 'runtime'
  | 'generic_indicator'

export interface MarketDetailFact {
  id: string
  label: string
  value: string
  tone: 'default' | 'up' | 'down' | 'warning' | 'unavailable'
  source: MarketDetailSource
  icon?: MarketDetailIconName
}

export interface MarketDetailDisclosureRow {
  label: string
  value: string
  source: MarketDetailSource
}

export interface MarketDetailDisclosureSection {
  id: string
  title: string
  summary: string
  updatedAt: string | null
  tone: 'default' | 'warning' | 'unavailable'
  rows: readonly MarketDetailDisclosureRow[]
}

export interface MarketDetailHeaderModel {
  symbol: string
  productName: string
  exchange: string
  sector: string
  seriesKind: SeriesKind
  displayContract: string | null
  asOf: string | null
  open: number | null
  high: number | null
  low: number | null
  close: number | null
  change: number | null
  pct: number | null
  volume: number | null
  turnover: number | null
  openInterest: number | null
  phase: string
  displaySource: string
  freshness: 'fresh' | 'stale' | 'unavailable'
  extendedSections: readonly MarketDetailDisclosureSection[]
}

/** A view-owned history entry; Slice A deliberately does not define strategy history semantics. */
export interface MarketDetailHistoryItem {
  id: string
  label: string
  occurredAt: string
  source: MarketDetailSource
}

export interface DetailViewModel {
  view: MarketDetailView
  identity: MarketDetailIdentity
  asOf: string | null
  semanticBanner: {
    text: string
    tone: 'info' | 'warning'
  }
  facts: readonly [MarketDetailFact, MarketDetailFact, MarketDetailFact]
  disclosureSections: readonly MarketDetailDisclosureSection[]
  history: readonly MarketDetailHistoryItem[]
  dataStatus: 'ready' | 'stale' | 'unavailable'
}
