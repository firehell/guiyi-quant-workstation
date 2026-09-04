const FORMULAS = [
  'newow_trend_band_page_v2',
  'newow_escape_d123_page_v2',
  'newow_cup_handle_v1',
  'newow_oscillation_hhv_llv10_page_v1',
  'newow_main_force_control_page_v1',
  'newow_main_rise_ma35_ma45_page_v1',
  'newow_target_absorb_hhv_llv10_page_v1',
  'newow_target_absorb_display_selection_page_v2',
  'newow_hhv_llv_window_optimizer_page_v1',
  'newow_hhv_llv_window_optimizer_causal_v1',
  'newow_composite_decision_page_v3_2_82',
  'newow_composite_decision_cleanroom_v1',
  'newow_first_action_principle_page_v3_2_63',
  'newow_diagnostic_facts_cleanroom_v1',
  'newow_diagnostic_rules_cleanroom_v1',
] as const

export function newowCalculationIdentity(product: string): string {
  return [
    'market_data_service:canonical_v2', 'main_contract_map:rank1:canonical_v1',
    product, 'actual_dominant', '1d+1w+60m', 'newow_trend_d1_page_v2', ...FORMULAS,
  ].join('|')
}

export function minimalNewowWire(product: string, from: string, through: string) {
  const calculation = newowCalculationIdentity(product)
  const barEnd = `${from}T07:00:00Z`
  const contract = `${product.toUpperCase()}2601`
  const segmentId = `${contract}:${from}:${through}`
  const pageWindow = (window: 10 | 20 | 24 | 30 | 52) => ({
    window, cumulative_return_pct: '0', max_drawdown_pct: '0', trade_count: 0,
    win_rate_pct: '0', score: '0', terminal_position_was_open: false,
    force_closed_at_end: true, execution_timing: 'same_bar_close',
    trustworthy_for_research: false, formula_version: 'newow_hhv_llv_window_optimizer_page_v1',
  })
  const frequency = (value: '1d' | '1w' | '60m', withPoint: boolean) => ({
    frequency: value,
    points: withPoint ? [{
      bar_end: barEnd, target: null, absorb: null, window: 10, available: false,
      formula_version: 'newow_target_absorb_hhv_llv10_page_v1',
    }] : [],
    owner_segment_ids: withPoint ? [segmentId] : [],
    formula_version: 'newow_target_absorb_hhv_llv10_page_v1',
  })
  return {
    meta: {
      strategy_code: 'newow_trend_v1', profile_id: 'newow_trend_d1_page_v2', frequency: '1d',
      series_kind: 'actual_dominant', calculation_identity: calculation, data_revision_identity: null,
      request_identity: `${calculation}:${from}:${through}`,
    },
    instrument: { product, display_name: null, last_visible_physical_contract: contract },
    bars: [{
      bar_end: barEnd, trading_day: from, open: '100', high: '101', low: '99', close: '100',
      volume: 1, open_interest: 1, physical_contract: contract, segment_id: segmentId,
      source_identity: calculation,
    }],
    bar_policy: 'completed_only',
    trend_band: [{ bar_end: barEnd, b_value: null, c_value: null, state: 'UNAVAILABLE', state_before: null, transition: null }],
    trend_markers: [], escape_markers: [], cup_markers: [], cup_handles: [], rollover_seams: [],
    price_channel: {
      daily: frequency('1d', true), weekly: frequency('1w', false), sixty_minute: frequency('60m', false),
      display: {
        target: null, absorb: null, raw_target: null, raw_absorb: null,
        target_period: null, absorb_period: null, target_branch_token: 'target_unavailable',
        absorb_branch_token: 'absorb_unavailable', formula_version: 'newow_target_absorb_display_selection_page_v2',
      },
    },
    page_window_comparison: [10, 20, 24, 30, 52].map(pageWindow),
    composite_page: null, composite_cleanroom: null,
    first_action_principle: {
      level: 'warn', rule_token: 'first_action_insufficient', fact_tokens: ['insufficient'],
      formula_version: 'newow_first_action_principle_page_v3_2_63',
    },
    diagnostic_facts: {
      as_of: barEnd, target_price: null, absorb_price: null, target_distance_pct: null,
      absorb_distance_pct: null, ema20: null, close_vs_ema20: 'unavailable',
      trend_state: 'UNAVAILABLE', trend_duration_bars: 0, oscillation_holding: null,
      main_force_status: null, main_rise_active: null, cup_state: null,
      weekly_signal: 'wait', daily_signal: 'wait', repainting_inputs_excluded: [], formula_versions: [],
    },
    diagnostic_tokens: [],
    semantic_labels: {
      page_parity: true, cleanroom_separated: true, observation_only: true,
      causal_research_result: false, repainting_input_used: false,
    },
    legend: { BUILD: 'trend build', CLEAR: 'trend clear', D1: 'escape D1', D2: 'escape D2', D3: 'escape D3' },
    formula_descriptions: {
      trend_band: FORMULAS[0], escape: FORMULAS[1], cup_handle: FORMULAS[2], oscillation: FORMULAS[3],
      main_force: FORMULAS[4], main_rise: FORMULAS[5], price_channel: FORMULAS[6],
      display_selection: FORMULAS[7], page_window_comparison: FORMULAS[8], causal_window_identity: FORMULAS[9],
      composite_page: FORMULAS[10], composite_cleanroom: FORMULAS[11], first_action: FORMULAS[12],
      diagnostic_facts: FORMULAS[13], diagnostic_rules: FORMULAS[14],
    },
    warnings: [
      'NEWOW_TREND_WARMUP_INSUFFICIENT', 'NEWOW_D123_WARMUP_INSUFFICIENT',
      'NEWOW_CUP_WARMUP_INSUFFICIENT', 'NEWOW_COMPOSITE_DAILY_BARS_INSUFFICIENT',
    ],
  }
}
