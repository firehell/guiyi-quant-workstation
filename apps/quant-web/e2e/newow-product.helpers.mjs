import { performance } from 'node:perf_hooks'

export const NEWOW_AS_OF = '2026-09-03T08:00:00.000Z'
export const NEWOW_PATH = '/market/chart?symbol=rb&view=newow&strategy=trend&frequency=1d&series_kind=actual_dominant'
export const NEWOW_STRATEGIES = ['trend', 'oscillation', 'main_rise']
export const NEWOW_FREQUENCIES = ['1w', '1d', '60m']

const CONTRACT = 'RB2605'
const SEGMENT = 'rb:RB2605:2026-01-01T00:00:00+00:00'
const HASH = {
  chart: 'a'.repeat(64), reference: 'b'.repeat(64), explanation: 'c'.repeat(64),
  comparator: 'd'.repeat(64), auxiliary: 'e'.repeat(64), page: 'f'.repeat(64),
}

export function newowRoute(strategy = 'trend', frequency = '1d', extra = '') {
  return `/market/chart?symbol=rb&view=newow&strategy=${strategy}&frequency=${frequency}&series_kind=actual_dominant${extra}`
}

export async function installNewowProductFixtures(page, options = {}) {
  const state = {
    requests: [], productRequests: [], unexpected: [], aborted: [],
    counts: new Map(), requestStartedAt: new Map(),
  }
  await page.addInitScript(() => {
    window.__newowBrowserClock = { installedAt: performance.now() }
    class FixtureWebSocket {
      static OPEN = 1
      static CLOSED = 3
      readyState = FixtureWebSocket.OPEN
      onopen = null
      onclose = null
      constructor(url) { this.url = url; queueMicrotask(() => this.onopen?.()) }
      close() { this.readyState = FixtureWebSocket.CLOSED; this.onclose?.() }
    }
    window.WebSocket = FixtureWebSocket
  })

  await page.route('**/*', async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    const startedAt = performance.now()
    if (url.origin === 'http://127.0.0.1:5182' && !url.pathname.startsWith('/api/')) return route.continue()
    state.requests.push({ url, method: request.method(), startedAt })
    if (request.method() !== 'GET') return unexpected(route, state, `non-GET ${request.method()} ${url.pathname}`)

    if (url.pathname === '/api/v1/market/newow/strategy-detail') {
      const section = url.searchParams.get('section') || 'chart'
      const strategy = url.searchParams.get('strategy') || 'trend'
      const frequency = url.searchParams.get('frequency') || '1d'
      const key = [strategy, frequency, section, url.searchParams.get('component') || '', url.searchParams.get('chart_before') || '', url.searchParams.get('history_before') || ''].join(':')
      const count = (state.counts.get(key) || 0) + 1
      state.counts.set(key, count)
      state.requestStartedAt.set(key, startedAt)
      state.productRequests.push({ url, section, strategy, frequency, key, count, startedAt })

      if (typeof options.onProductRequest === 'function') {
        const decision = await options.onProductRequest({ route, url, section, strategy, frequency, key, count, state })
        if (decision === 'handled') return
      }
      const conflictKey = `${strategy}:${frequency}:${section}`
      if (options.conflictOnce === conflictKey && count === 1) {
        return route.fulfill({ status: 409, json: { detail: { code: 'NEWOW_SNAPSHOT_GENERATION_CONFLICT' } } })
      }
      if (options.busy === conflictKey) {
        return route.fulfill({ status: 429, json: { detail: { code: 'NEWOW_RESOURCE_BUSY' } } })
      }
      if (options.identityMismatch === conflictKey) {
        const payload = envelope(url, section, strategy, frequency, options)
        payload.meta.identity.frequency = frequency === '1d' ? '1w' : '1d'
        return route.fulfill({ json: payload })
      }
      return route.fulfill({ json: envelope(url, section, strategy, frequency, options) })
    }

    if (url.pathname === '/api/v1/market/dominants') {
      return route.fulfill({ json: { items: [{ product: 'rb', product_name: '螺纹钢', sector: '黑色', exchange: 'SHFE', actual_contract: CONTRACT, dominant_mapping_date: '2026-09-03' }] } })
    }
    if (url.pathname === '/api/v1/market/research/product') return route.fulfill({ json: researchProduct() })
    if (url.pathname === '/api/v1/market/state') return route.fulfill({ json: marketState(url) })
    if (url.pathname === '/api/v1/market/bars/page') {
      if (options.genericSeries === 'pending') return new Promise(() => {})
      if (options.genericSeries === 'failed') return route.abort('failed')
      return route.fulfill({ json: genericBarsPage(url) })
    }
    if (url.pathname === '/api/v1/market/newow/trend-detail') {
      return route.abort('failed')
    }
    if (url.pathname === '/api/alerts/events') return route.fulfill({ json: { items: alertEvents(url) } })
    if (url.pathname.startsWith('/api/alerts/products/')) {
      const symbol = url.pathname.split('/').at(-1)
      return route.fulfill({ json: { symbol, rules: alertRules() } })
    }
    if (url.pathname === '/api/alerts/current-events') {
      return route.fulfill({ json: { status: 'ready', trading_day: '2026-09-03', items: alertEvents(url) } })
    }
    if (url.pathname === '/api/runtime/health') return route.fulfill({ json: runtimeHealth() })
    if (url.pathname === '/api/v1/market/research/home-overview') return route.fulfill({ json: homeOverview() })
    return unexpected(route, state, `${request.method()} ${url.href}`)
  })
  return state
}

function unexpected(route, state, message) {
  state.unexpected.push(message)
  return route.abort('blockedbyclient')
}

function envelope(url, section, strategy, frequency, options) {
  const wrappers = {
    chart: notRequested(), auxiliary: notRequested(), reference: notRequested(),
    explanation: notRequested(), comparator: notRequested(),
  }
  let status = ready()
  let value
  if (section === 'chart') value = chartValue(url, strategy, frequency, options)
  else if (section === 'reference') value = referenceValue(url, strategy, frequency, options)
  else if (section === 'auxiliary') {
    const component = url.searchParams.get('component') || 'main_force_control'
    if (options.auxiliaryState?.[component]) {
      status = options.auxiliaryState[component]
      value = null
    } else value = auxiliaryValue(component, frequency)
  } else if (section === 'explanation') value = explanationValue(strategy, frequency, url.searchParams.get('as_of') || NEWOW_AS_OF)
  else value = comparatorValue(strategy, frequency, url.searchParams.get('as_of') || NEWOW_AS_OF)
  wrappers[section] = delivered(status, value)
  return { meta: meta(url, strategy, frequency, section, options), section, ...wrappers }
}

function meta(url, strategy, frequency, section, options) {
  const revision = options.revision || 'fixture-revision-1'
  return {
    schema_version: 'newow_product_detail_v1',
    identity: { product: 'rb', strategy, frequency, series_kind: 'actual_dominant', profile_id: `newow_product_${strategy}_${frequency}_v1`, formula_versions: formulas(strategy) },
    as_of: url.searchParams.get('as_of') || NEWOW_AS_OF,
    read_at: '2026-09-03T08:00:01.000Z', input_content_sha256: HASH[section] || HASH.chart,
    data_revision_identity: revision, snapshot_token: `snapshot:${strategy}:${frequency}:${revision}`,
    reference_model_version: 'newow_marker_reference_zero_cost_v1',
    futures_adaptation_version: 'newow_futures_segment_interrupt_v1',
  }
}

function formulas(strategy) {
  if (strategy === 'trend') return ['newow_escape_d123_page_v2', 'newow_trend_band_page_v2']
  if (strategy === 'oscillation') return ['newow_hhv_llv_channel_page_v1', 'newow_oscillation_hhv_llv10_page_v1']
  return ['newow_buy_d456_page_v1', 'newow_escape_d123_page_v2', 'newow_magic11_page_v1', 'newow_main_rise_j_reduce_page_v1', 'newow_main_rise_ma35_ma45_page_v1']
}

function chartValue(url, strategy, frequency, options) {
  const before = url.searchParams.get('chart_before')
  const locateFrom = url.searchParams.get('from')
  const long = options.longHistory === true
  const count = long ? (before ? 360 : 480) : 24
  const offset = before ? 0 : long ? 360 : 40
  let bars = Array.from({ length: count }, (_, index) => productBar(frequency, index + offset))
  if (locateFrom === '2026-01-05') bars = [productBarAt(frequency, '2026-01-05T07:00:00.000Z', '2026-01-05', 96)]
  const values = strategy === 'trend'
    ? (close) => ({ b: String(close - 2), a: String(close + 2) })
    : strategy === 'oscillation'
      ? (close) => ({ upper: String(close + 5), lower: String(close - 5) })
      : (close) => ({ ma35: String(close - 1), ma45: String(close - 2) })
  const actions = []
  if (!options.noAction && !before) {
    const first = bars.at(-2)
    const last = bars.at(-1)
    if (locateFrom === '2026-01-05') actions.push(action('historic-build', 'BUILD', bars[0], strategy, 0))
    else if (strategy === 'oscillation') actions.push(
      action(id(strategy, frequency, 'build-old'), 'BUILD', first, strategy, 0),
      action(id(strategy, frequency, 'clear-same'), 'CLEAR', last, strategy, 0, id(strategy, frequency, 'build-old')),
      action(id(strategy, frequency, 'build-same'), 'BUILD', last, strategy, 1),
    )
    else actions.push(action(id(strategy, frequency, 'build'), 'BUILD', first, strategy, 0), action(id(strategy, frequency, 'clear'), 'CLEAR', last, strategy, 0, id(strategy, frequency, 'build')))
  }
  const hints = options.noAction || before ? [] : [{ hint_id: id(strategy, frequency, 'hint-d4'), kind: 'D4', bar_end: bars.at(-1).bar_end, known_at: bars.at(-1).bar_end, anchor_price: String(Number(bars.at(-1).close) - 0.5), physical_contract: CONTRACT, segment_id: SEGMENT, retrospective: false, quantity_effect: 'none', sequence: null }]
  return {
    chart_from: '2026-01-01', chart_through: '2026-09-03', page_identity: HASH.page,
    bars,
    frames: bars.map((bar) => ({ bar_end: bar.bar_end, main_state: actions.some((item) => item.bar_end === bar.bar_end && item.kind === 'BUILD') ? 'BUILD' : 'HOLD', main_values: values(Number(bar.close)), status: ready(), action_ids: actions.filter((item) => item.bar_end === bar.bar_end).map((item) => item.signal_id), hint_ids: hints.filter((item) => item.bar_end === bar.bar_end).map((item) => item.hint_id) })),
    actions,
    hints,
    diagnostics: options.noAction ? ['NO_MAIN_ACTION_IS_VALID'] : [], next_before: before || locateFrom ? null : 'chart-page-2',
    repainting: false, formal_signal_eligible: true, allowed_uses: ['product_chart', 'reference_input'],
  }
}

function referenceValue(url, strategy, frequency, options) {
  const page = Boolean(url.searchParams.get('history_before'))
  const zero = options.zeroClosed === true
  const summary = {
    membership_policy: 'entry_in_window_v1', closed_count: zero ? 0 : 1, win_count: zero ? 0 : 1, loss_count: 0, flat_count: 0,
    win_rate_pct: zero ? null : '100', mean_return_pct: zero ? null : '5.1020', sum_return_percentage_points: zero ? null : '5.1020',
    open_count: 1, interrupted_count: 1, initial_count: 1,
  }
  const recent = productBar(frequency, 63)
  const prior = productBar(frequency, 62)
  const closed = trade(id(strategy, frequency, 'closed'), strategy, frequency, prior, recent, 'CLOSED', '5.1020', null, strategy === 'oscillation' ? id(strategy, frequency, 'build-old') : id(strategy, frequency, 'build'))
  const open = trade(id(strategy, frequency, 'open'), strategy, frequency, recent, null, 'OPEN', null, '-1.2500', strategy === 'oscillation' ? id(strategy, frequency, 'build-same') : id(strategy, frequency, 'build'))
  const interruptedBar = productBarAt(frequency, '2026-01-05T07:00:00.000Z', '2026-01-05', 90)
  const interrupted = trade(id(strategy, frequency, 'interrupted'), strategy, frequency, interruptedBar, null, 'ROLLOVER_INTERRUPTED', null, '-10.0000', 'historic-build')
  const initial = { ...closed, reference_trade_id: id(strategy, frequency, 'initial'), statistics_membership: 'initial_before_window', entry_signal_id: 'historic-build', entry_bar_end: '2023-11-20T07:00:00.000Z', entry_trading_day: '2023-11-20' }
  return {
    performance_since: '2026-01-01', performance_through: '2026-09-03', actual_available_through: '2026-09-03', reference_cutoff: url.searchParams.get('as_of') || NEWOW_AS_OF,
    reference_input_sha256: HASH.reference, summary, items: page ? [interrupted, initial] : [open, ...(zero ? [] : [closed])], next_before: page ? null : 'reference-page-2',
    executable: false, auto_order: false, allowed_uses: ['page_parity_reference', 'research_display'],
  }
}

function trade(tradeId, strategy, frequency, entry, exit, status, result, mark = null, entrySignalId = null) {
  const suffix = status === 'OPEN' ? 'open' : status === 'ROLLOVER_INTERRUPTED' ? 'interrupted' : 'build'
  return {
    reference_trade_id: tradeId, product: 'rb', strategy_code: strategy, frequency, physical_contract: CONTRACT, segment_id: SEGMENT,
    formula_versions: formulas(strategy), reference_model_version: 'newow_marker_reference_zero_cost_v1', futures_adaptation_version: 'newow_futures_segment_interrupt_v1',
    entry_signal_id: entrySignalId || id(strategy, frequency, suffix), entry_sequence: 0, entry_bar_end: entry.bar_end, entry_trading_day: entry.trading_day, entry_reference_price: strategy === 'oscillation' ? entry.low : strategy === 'main_rise' ? String(Number(entry.close) - 2) : String(Number(entry.close) - 2),
    exit_signal_id: exit ? id(strategy, frequency, 'clear') : null, exit_bar_end: exit?.bar_end || null, exit_trading_day: exit?.trading_day || null, exit_reference_price: exit ? String(Number(exit.close) + (strategy === 'oscillation' ? 5 : -2)) : null,
    status, holding_bars: 1, reference_return_pct: result, mark_bar_end: exit ? null : entry.bar_end, mark_reference_price: exit ? null : entry.close, mark_change_pct: mark,
    interrupted_at: status === 'ROLLOVER_INTERRUPTED' ? '2026-01-06T00:00:00.000Z' : null, interruption_reason: status === 'ROLLOVER_INTERRUPTED' ? 'OWNER_BOUNDARY' : null,
    statistics_membership: 'entry_in_window_v1', hint_ids: status === 'OPEN' ? [id(strategy, frequency, 'hint-d4'), 'hint-not-loaded'] : [],
  }
}

function action(signalId, kind, owner, strategy, sequence, related = null) {
  const reference = strategy === 'oscillation' ? (kind === 'BUILD' ? owner.low : owner.high) : String(Number(owner.close) - 2)
  return { signal_id: signalId, kind, bar_end: owner.bar_end, trading_day: owner.trading_day, reference_price: reference, physical_contract: CONTRACT, segment_id: SEGMENT, related_build_id: related, trade_eligibility: 'ELIGIBLE', sequence }
}

function auxiliaryValue(component, frequency) {
  const base = { component, segments: [], repainting: false, formal_signal_eligible: true, page_parity: false, source_category: 'guiyi_product_auxiliary_adapter', allowed_uses: ['product_display'] }
  if (component === 'cup_handle') return { ...base, formula_version: 'newow_cup_handle_v1', segments: frequency === '1d' ? [{ physical_contract: CONTRACT, segment_id: SEGMENT, bar_ends: ['2026-09-03T07:00:00.000Z'], status: ready(), data: [] }] : [] }
  const barEnds = ['2026-09-02T07:00:00.000Z', '2026-09-03T07:00:00.000Z']
  if (component === 'main_force_control') return { ...base, formula_version: 'newow_main_force_control_page_v1', segments: [{ physical_contract: CONTRACT, segment_id: SEGMENT, bar_ends: barEnds, status: ready(), data: { kongpan: [10, 12], status: ['HOLD', 'BUILD'], current_status: 'BUILD', formula_version: 'newow_main_force_control_page_v1' } }] }
  if (component === 'up_down_energy') return { ...base, formula_version: 'newow_up_down_energy_page_v1', segments: [{ physical_contract: CONTRACT, segment_id: SEGMENT, bar_ends: barEnds, status: ready(), data: { var4: [1, 2], ma10: [1, 1.5], band_entry: [0, 1], rebound_entry: [0, 0], oversold_entry: [0, 0], var3: [1, 2], ma120: [1, 1], formula_version: 'newow_up_down_energy_page_v1' } }] }
  return { ...base, formula_version: 'newow_zhaoyao_mirror_repainting_page_v1', repainting: true, formal_signal_eligible: false, segments: [{ physical_contract: CONTRACT, segment_id: SEGMENT, bar_ends: barEnds, status: ready(), data: { entry: [0, 1], wash: [1, 0], distribution: [0, 0], markup: [1, 2], exit: [0, 0], inducement: [0, 0], peaks: [1, 2], caution: [0, 1], repainting: true, formal_signal_eligible: false, formula_version: 'newow_zhaoyao_mirror_repainting_page_v1' } }] }
}

function explanationValue(strategy, frequency, asOf) {
  const slot = (slotFrequency, barEnd, state) => ({
    frequency: slotFrequency, as_of: asOf, availability: ready(), confirmation_status: ready(),
    identity: { product: 'rb', strategy, frequency: slotFrequency, series_kind: 'actual_dominant', profile_id: `newow_product_${strategy}_${slotFrequency}_v1`, formula_versions: formulas(strategy) },
    bar_end: barEnd, source_identity: `canonical:rb:${CONTRACT}:${slotFrequency}`, physical_contract: CONTRACT, segment_id: SEGMENT, formula_versions: formulas(strategy), main_state: state,
  })
  const gap = evidenceRequired('NEWOW_PRIVATE_SCORE_UNPROVEN')
  return {
    context: { as_of: asOf, weekly: slot('1w', '2026-08-28T07:00:00.000Z', 'HOLD'), daily: slot('1d', '2026-09-02T07:00:00.000Z', 'BUILD'), hourly: slot('60m', '2026-09-03T07:00:00.000Z', 'HOLD'), missing_frequencies: [], recompute_mode: 'strict_before', historical_database_knowledge_reconstructed: false },
    composite: { status: 'ready', evidence_status: 'RESEARCH_EVIDENCE_ONLY', reason_code: null, as_of: asOf, formula_versions: ['newow_composite_decision_page_v3_2_82'], source_bars: [], value: {
      decision: { source_key: 'fixture', selected_key: 'long', label: '偏多', position_range: '30%-50%', fallback_used: false, warning_branches_unreachable: true, position_is_target: false, position_is_hand_count: false, formula_version: 'newow_composite_decision_page_v3_2_82' },
      direction: { token: 'LONG_BIAS', certainty_points: 2, formula_version: 'direction-v1' }, certainty: { trend: 2, oscillation: 2, alignment: 1, direction: 2, uncapped_total: 7, total: 7, cap: null, is_probability: false, is_win_rate: false, formula_version: 'certainty-v1' },
      volatility: { value_pct: '1.2500', level: 'medium', true_range_count: 20, method: 'ATR20_CLOSE', is_wilder_atr: false, formula_version: 'volatility-v1' },
      first_action: { rule_token: 'WAIT_CONFIRM', level: 'notice', page_title: '等待', page_detail: '等待已完成周期确认', token_owner: 'guiyi', token_is_page_native: false, page_formula_version: 'first-action-v1' },
      week_day_matrix: { key: 'fixture', name: '周日组合', risk: '中', position: '30%-50%', formula_version: 'matrix-v1' }, subfeatures: [{ name: 'private-score', status: gap, value: null }], input_facts: [], warning_branches_unreachable: true, diagnostic_tokens: null, ai_copy: null, six_combo_ranking: null,
      evidence_manifest_sha256: '1'.repeat(64), page_source_sha256: '2'.repeat(64), reachability_sha256: '3'.repeat(64), ai_template_evidence_sha256: '4'.repeat(64), frozen_results_sha256: '5'.repeat(64),
    } },
    target_absorb: { status: 'evidence_required', evidence_status: 'EVIDENCE_REQUIRED', reason_code: 'NEWOW_TARGET_SOURCE_UNPROVEN', as_of: asOf, display_surface: null, formula_versions: [], source_bars: [], decision_facts: [], value: null },
    sources: ['1w', '1d', '60m'].map((sourceFrequency) => ({ role: `${sourceFrequency}-context`, source_category: 'strategy_replay', adapter_version: 'v1', formula_versions: formulas(strategy), frequency: sourceFrequency, bar_end: slot(sourceFrequency, sourceFrequency === '1w' ? '2026-08-28T07:00:00.000Z' : sourceFrequency === '1d' ? '2026-09-02T07:00:00.000Z' : '2026-09-03T07:00:00.000Z', 'HOLD').bar_end, physical_contract: CONTRACT, segment_id: SEGMENT, as_of: asOf, dependency_sha256: '6'.repeat(64), status: 'ready', reason_code: null })),
    page_parity: false, allowed_uses: ['research_explanation', 'product_display'],
  }
}

function comparatorValue(strategy, frequency, asOf) {
  const windows = [10, 20, 24, 30, 52].map((window) => ({ window, cumulative_return_pct: `${window / 10}`, max_drawdown_pct: '-1', trade_count: 1, win_count: 1, loss_count: 0, win_rate_pct: '100', force_closed_at_end: true, score: '1', page_display: { cumulative_return_pct: `${window / 10}`, max_drawdown_pct: '-1', win_rate_pct: '100' }, trades: [{ entry_bar_end: '2026-01-05T07:00:00.000Z', entry_price: '100', exit_bar_end: NEWOW_AS_OF, exit_price: '101', return_pct: '1', won: true, synthetic_terminal: true }] }))
  const sourceBars = { count: 120, first_trading_day: '2026-01-01', last_trading_day: '2026-09-03', first_bar_end: '2026-01-05T07:00:00.000Z', last_bar_end: '2026-09-03T07:00:00.000Z', source_identities: ['canonical'], snapshot_kind: 'canonical', fact_identity_fields: ['bar_end', 'physical_contract', 'segment_id'] }
  return { result: { identity: { product: 'rb', strategy, frequency, series_kind: 'actual_dominant', profile_id: `newow_product_${strategy}_${frequency}_v1`, formula_versions: formulas(strategy) }, status: 'ready', evidence_status: 'RESEARCH_EVIDENCE_ONLY', reason_code: null, as_of: asOf, formula_versions: ['newow_hhv_llv_window_optimizer_page_v1'], source_bars: [sourceBars], value: { segments: [{ physical_contract: CONTRACT, segment_id: SEGMENT, frequency, authoritative_start_trading_day: '2026-01-01', authoritative_end_trading_day: '2026-09-03', source_bars: sourceBars, as_of: asOf, in_sample: true, repainting: false, repaint_status: ready(), input_snapshot_status: ready(), status: ready(), results: windows, ranked_windows: [52, 30, 24, 20, 10] }], default_segment_id: SEGMENT, candidate_windows: [10, 20, 24, 30, 52], page_formula_version: 'newow_hhv_llv_window_optimizer_page_v1', futures_adapter_version: 'newow_futures_segment_comparator_v1', page_source_kernel_page_parity: true, futures_adapter_page_parity: false, in_sample: true, executable: false, input_mode: 'canonical', subfeatures: [] } }, executable: false, page_parity: false, synthetic_terminal_is_reference_exit: false, allowed_uses: ['in_sample_comparison'] }
}

function productBar(frequency, index) {
  if (frequency === '60m') {
    const base = Date.UTC(2026, 6, 1, 1)
    const time = new Date(base + index * 60 * 60 * 1000)
    return productBarAt(frequency, time.toISOString(), time.toISOString().slice(0, 10), 100 + index / 10)
  }
  const step = frequency === '1w' ? 7 : 1
  const base = frequency === '1w' ? Date.UTC(2025, 0, 1, 7) : Date.UTC(2023, 11, 1, 7)
  const time = new Date(base + index * step * 24 * 60 * 60 * 1000)
  return productBarAt(frequency, time.toISOString(), time.toISOString().slice(0, 10), 100 + index / 10)
}
function productBarAt(frequency, barEnd, tradingDay, close) { return { bar_end: barEnd, trading_day: tradingDay, open: String(close - 1), high: String(close + 2), low: String(close - 2), close: String(close), volume: 1000, open_interest: 2000, physical_contract: CONTRACT, segment_id: SEGMENT, source_identity: `canonical:rb:${CONTRACT}:${frequency}`, observation_eligible: true, completed: true } }
function genericBarsPage(url) { const frequency = url.searchParams.get('frequency') || '15m'; const bars = [0, 1].map((index) => { const bar = productBar(frequency === '1w' || frequency === '1d' || frequency === '60m' ? frequency : '60m', 60 + index); return { ...bar, open: Number(bar.open), high: Number(bar.high), low: Number(bar.low), close: Number(bar.close), turnover: 10000 } }); return { request: { series_kind: url.searchParams.get('series_kind'), symbol: url.searchParams.get('symbol'), contract: url.searchParams.get('contract'), frequency, before: url.searchParams.get('before'), limit: Number(url.searchParams.get('limit') || 500) }, bars, canonical_coverage: { start: bars[0].bar_end, end: bars.at(-1).bar_end }, page: { has_more_before: false, next_before: null }, resolved_contract_segments: [{ contract: CONTRACT, start_trading_day: bars[0].trading_day, end_trading_day: bars.at(-1).trading_day }] } }
function researchProduct() { return { symbol: 'rb', product_name: '螺纹钢', sector: '黑色', exchange: 'SHFE', series_kind: 'actual_dominant', contract: null, as_of: NEWOW_AS_OF, current_dominant: CONTRACT, dominant_mapping_date: '2026-09-03', daily_trend: 'neutral', weekly_trend: 'neutral', position20: null, distance_to_20d_high: null, distance_to_20d_low: null, volume_ratio20: null, oi_change_1d: null, turnover_change_5d: null, atr14_percentile252: null, recent_daily: [] } }
function marketState(url) { return { symbol: url.searchParams.get('symbol') || 'rb', series_kind: url.searchParams.get('series_kind') || 'actual_dominant', frequency: url.searchParams.get('frequency') || '15m', operational: true, phase: 'CLOSED', trading_day: '2026-09-03', live_eligible: false, live_available: false, live_contract: null, canonical_end: NEWOW_AS_OF, after_market: { last_successful_trading_day: '2026-09-03' } } }
function runtimeHealth() { return { status: 'ok', generated_at: NEWOW_AS_OF, readonly: true, would_start_services: false, would_enqueue_jobs: false, would_send_notifications: false, components: { alert: { status: 'ok', enabled_rule_count: 0, rule_status: { htdy_original_15m: { last_evaluated_bar_at: null, last_event_at: null, last_failure_at: null, error_type: null }, subing_ths_alert_15m_v1: { last_evaluated_bar_at: null, last_event_at: null, last_failure_at: null, error_type: null } } } } } }
function alertRules() { return [{ rule_code: 'htdy_original_15m', display_name: '火天大有', kind: 'indicator_observation', input_frequencies: ['15m'], enabled_for_product: true, enabled_frequencies: ['15m'] }, { rule_code: 'subing_ths_alert_15m_v1', display_name: '苏冰预警', kind: 'indicator_observation', input_frequencies: ['15m'], enabled_for_product: false, enabled_frequencies: [] }] }
function alertEvents(url) { const rule = url.searchParams.get('rule_code'); return rule ? [{ id: rule === 'htdy_original_15m' ? 1 : 2, rule_code: rule, symbol: 'rb', contract: CONTRACT, trading_day: '2026-09-03', frequency: '15m', bar_end: '2026-09-03T02:45:00.000Z', result_codes: ['buy'], detected_at: '2026-09-03T02:46:00.000Z', notification_attempted_at: null }] : [] }
function homeOverview() { return { status: 'ready', target_as_of: '2026-09-03', data_as_of: '2026-09-03', freshness: 'fresh', active_count: 1, participant_count: 1, stale_count: 0, unavailable_count: 0, summary: { price_up_count: 1, price_down_count: 0, price_flat_count: 0, daily_up_count: 1, daily_down_count: 0, daily_neutral_count: 0, daily_unavailable_count: 0, aligned_up_count: 1, aligned_down_count: 0 }, items: [{ symbol: 'rb', product_name: '螺纹钢', sector: '黑色', exchange: 'SHFE', actual_contract: CONTRACT, dominant_mapping_date: '2026-09-03', data_as_of: '2026-09-03', close: '100', price_change_1d: '0.01', price_change_5d: null, volume_ratio20: '1.2', oi_change_1d: null, atr14_percentile252: null, daily_trend: 'up', weekly_trend: 'up', reason_codes: [] }], sectors: [{ sector: '黑色', active_count: 1, participant_count: 1, median_price_change_1d: '0.01' }] } }
function id(strategy, frequency, suffix) { return `${strategy}-${frequency}-${suffix}` }
function ready() { return { status: 'ready', evidence_status: 'ACTIVE_CODE_VERIFIED', reason_code: null } }
export function warming(reason = 'NEWOW_WARMING') { return { status: 'warming', evidence_status: 'ACTIVE_CODE_VERIFIED', reason_code: reason } }
export function unavailable(reason = 'NEWOW_AUXILIARY_UNAVAILABLE') { return { status: 'unavailable', evidence_status: 'ACTIVE_CODE_VERIFIED', reason_code: reason } }
export function evidenceRequired(reason = 'NEWOW_EVIDENCE_REQUIRED') { return { status: 'evidence_required', evidence_status: 'EVIDENCE_REQUIRED', reason_code: reason } }
function delivered(status, value) { return { delivery: 'delivered', status, value } }
function notRequested() { return { delivery: 'not_requested', status: null, value: null } }

export function productRequests(state, section) { return state.productRequests.filter((item) => item.section === section) }
export function assertNoUnexpectedRequests(state) { if (state.unexpected.length) throw new Error(`unexpected requests: ${state.unexpected.join(', ')}`) }
