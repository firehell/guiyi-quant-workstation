export type NewowTrendBandState = 'UNAVAILABLE' | 'YELLOW' | 'BLUE'
export type NewowTrendTransition = 'BUILD' | 'CLEAR'
export type NewowTrendMarkerType = NewowTrendTransition
export type NewowEscapeMarkerType = 'NEWOW_ESCAPE_D1' | 'NEWOW_ESCAPE_D2' | 'NEWOW_ESCAPE_D3'
export type NewowCupMarkerType =
  | 'CUP_HANDLE_READY'
  | 'CUP_HANDLE_BREAKOUT'
  | 'CUP_HANDLE_WEAKENED'
  | 'CUP_HANDLE_INVALIDATED'
  | 'CUP_HANDLE_EXPIRED'
export type NewowMarkerType = NewowTrendMarkerType | NewowEscapeMarkerType | NewowCupMarkerType
export type NewowCupDirection = 'BULLISH' | 'BEARISH'
export type NewowCupState = 'FORMING' | 'READY' | 'BREAKOUT' | 'WEAKENED' | 'INVALIDATED' | 'EXPIRED'
export type NewowWarning =
  | 'NEWOW_TREND_WARMUP_INSUFFICIENT'
  | 'NEWOW_D123_WARMUP_INSUFFICIENT'
  | 'NEWOW_CUP_WARMUP_INSUFFICIENT'

export type NewowJsonValue =
  | null
  | string
  | number
  | boolean
  | readonly NewowJsonValue[]
  | { readonly [key: string]: NewowJsonValue }

export interface NewowTrendQueryIdentity {
  readonly symbol: string
  readonly from: string
  readonly through: string
}

export interface NewowMeta {
  readonly strategy_code: 'newow_trend_v1'
  readonly profile_id: 'newow_trend_d1_v1'
  readonly frequency: '1d'
  readonly series_kind: 'actual_dominant'
  readonly calculation_identity: string
  readonly data_revision_identity: string | null
  readonly request_identity: string
}

export interface NewowInstrument {
  readonly product: string
  readonly display_name: string | null
  readonly last_visible_physical_contract: string | null
}

export interface NewowBar {
  readonly bar_end: string
  readonly trading_day: string
  readonly open: number
  readonly high: number
  readonly low: number
  readonly close: number
  readonly volume: number
  readonly open_interest: number | null
  readonly physical_contract: string
  readonly segment_id: string
  readonly source_identity: string
}

export interface NewowTrendBandPoint {
  readonly bar_end: string
  readonly b_value: number | null
  readonly c_value: number | null
  readonly state: NewowTrendBandState
  readonly state_before: NewowTrendBandState | null
  readonly transition: NewowTrendTransition | null
}

export interface NewowMarker<T extends NewowMarkerType = NewowMarkerType> {
  readonly marker_id: string
  readonly marker_type: T
  readonly bar_end: string
  readonly price: number
  readonly label: string
  readonly color_token: string
  readonly priority: number
  readonly related_marker_ids: readonly string[]
  readonly trigger_facts: Readonly<Record<string, NewowJsonValue>>
  readonly formula_version: string
}

export interface NewowCupPivot {
  readonly pivot_at: string
  readonly confirmed_at: string
  readonly price: number
}

export interface NewowCupHandle {
  readonly candidate_id: string
  readonly direction: NewowCupDirection
  readonly state: NewowCupState
  readonly left_rim: NewowCupPivot
  readonly bottom: NewowCupPivot
  readonly right_rim: NewowCupPivot
  readonly handle_start_at: string
  readonly handle_extreme: NewowCupPivot | null
  readonly pivot_price: number | null
  readonly pivot_frozen_at: string | null
  readonly confirmed_at: string
  readonly first_seen_at: string
  readonly state_changed_at: string
  readonly score: number
  readonly score_breakdown: Readonly<Record<string, number>>
  readonly hard_failures: readonly string[]
  readonly diagnostics: readonly string[]
  readonly volume_facts: Readonly<Record<string, number>>
  readonly formula_version: 'newow_cup_handle_v1'
}

export interface NewowRolloverSeam {
  readonly trading_day: string
  readonly previous_contract: string
  readonly next_contract: string
  readonly previous_bar_end: string
  readonly next_bar_end: string
  readonly previous_segment_id: string
  readonly next_segment_id: string
}

export interface NewowLegend {
  readonly BUILD: 'trend build'
  readonly CLEAR: 'trend clear'
  readonly D1: 'escape D1'
  readonly D2: 'escape D2'
  readonly D3: 'escape D3'
}

export interface NewowFormulaDescriptions {
  readonly trend_band: 'newow_trend_band_cleanroom_v1'
  readonly escape: 'newow_escape_d123_v1'
  readonly cup_handle: 'newow_cup_handle_v1'
}

export interface NewowTrendDetailResponse {
  readonly meta: NewowMeta
  readonly instrument: NewowInstrument
  readonly bars: readonly NewowBar[]
  readonly bar_policy: 'completed_only'
  readonly trend_band: readonly NewowTrendBandPoint[]
  readonly trend_markers: readonly NewowMarker<NewowTrendMarkerType>[]
  readonly escape_markers: readonly NewowMarker<NewowEscapeMarkerType>[]
  readonly cup_markers: readonly NewowMarker<NewowCupMarkerType>[]
  readonly cup_handles: readonly NewowCupHandle[]
  readonly rollover_seams: readonly NewowRolloverSeam[]
  readonly legend: NewowLegend
  readonly formula_descriptions: NewowFormulaDescriptions
  readonly warnings: readonly NewowWarning[]
}
