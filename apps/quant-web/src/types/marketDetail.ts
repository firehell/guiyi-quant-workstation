import type { AlertEvent, MarketFrequency, SeriesKind } from './market.ts'

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
