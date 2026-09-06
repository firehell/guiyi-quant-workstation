import type {
  NewowProductHint,
  NewowProductDisplayState,
  NewowProductSection,
  NewowProductSectionResponse,
  NewowReferenceTrade,
  NewowResourceLifecycle,
} from '../types/newowProduct.ts'

export interface NewowProductSectionViewModel {
  readonly section: NewowProductSection
  readonly state: NewowProductDisplayState
  readonly reasonCode: string | null
  readonly staleReadAt: string | null
}

export function buildNewowProductSectionViewModel(input: {
  readonly section: NewowProductSection
  readonly response: NewowProductSectionResponse | null
  readonly lifecycle: NewowResourceLifecycle
}): NewowProductSectionViewModel {
  let state: NewowProductDisplayState = input.lifecycle
  if (input.lifecycle === 'ready' && input.response !== null) {
    if (input.response.status.status !== 'ready') state = input.response.status.status
    else if (input.section === 'chart' && input.response.section === 'chart' && input.response.value?.actions.length === 0) state = 'no_action'
    else if (input.section === 'reference' && input.response.section === 'reference' && input.response.value?.summary.closed_count === 0) state = 'empty_closed'
  }
  return {
    section: input.section,
    state,
    reasonCode: input.response?.status.reason_code ?? null,
    staleReadAt: input.lifecycle === 'stale' ? input.response?.meta.read_at ?? null : null,
  }
}

export type NewowReferenceCategory = 'closed' | 'open' | 'interrupted' | 'initial'

export interface NewowReferenceHintViewModel {
  readonly id: string
  readonly availability: 'loaded' | 'unavailable'
  readonly text: string
  readonly fact: NewowProductHint | null
}

export interface NewowReferenceRowViewModel {
  readonly id: string
  readonly trade: NewowReferenceTrade
  readonly category: NewowReferenceCategory
  readonly statusText: string
  readonly returnText: string
  readonly valuationText: string
  readonly hints: readonly NewowReferenceHintViewModel[]
}

export interface NewowReferencePanelViewModel {
  readonly summary: {
    readonly closedCount: number
    readonly winRateText: string
    readonly meanText: string
    readonly sumText: string
    readonly sumUnit: '百分点（简单相加）'
  }
  readonly counts: {
    readonly open: number
    readonly interrupted: number
    readonly initial: number
  }
  readonly performanceWindow: {
    readonly since: string
    readonly through: string
    readonly cutoff: string
  }
  readonly actualAvailableThrough: string
  readonly rows: readonly NewowReferenceRowViewModel[]
  readonly nextBefore: string | null
}

/** Projects server-owned reference facts for display without calculating returns or aggregates. */
export function buildNewowReferencePanelViewModel(
  response: NewowProductSectionResponse<'reference'>,
  chart: NewowProductSectionResponse<'chart'> | null,
): NewowReferencePanelViewModel {
  if (response.value === null) throw new Error('Newow reference value is unavailable')
  const value = response.value
  const loadedHints = new Map((chart?.value?.hints ?? []).map((hint) => [hint.hint_id, hint]))
  return {
    summary: {
      closedCount: value.summary.closed_count,
      winRateText: percentageText(value.summary.win_rate_pct),
      meanText: percentageText(value.summary.mean_return_pct),
      sumText: percentageText(value.summary.sum_return_percentage_points),
      sumUnit: '百分点（简单相加）',
    },
    counts: {
      open: value.summary.open_count,
      interrupted: value.summary.interrupted_count,
      initial: value.summary.initial_count,
    },
    performanceWindow: {
      since: value.performance_since,
      through: value.performance_through,
      cutoff: value.reference_cutoff,
    },
    actualAvailableThrough: value.actual_available_through,
    rows: value.items.map((trade) => referenceRow(trade, loadedHints)),
    nextBefore: value.next_before,
  }
}

export function filterNewowReferenceRows(
  model: NewowReferencePanelViewModel,
  filter: 'all' | NewowReferenceCategory | string,
): NewowReferencePanelViewModel {
  if (filter === 'all') return model
  return { ...model, rows: model.rows.filter((row) => row.category === filter) }
}

export type NewowReferenceLocate =
  | { readonly kind: 'loaded'; readonly signalId: string; readonly barEnd: string }
  | { readonly kind: 'request_display_window'; readonly signalId: string; readonly barEnd: string; readonly displayWindow: { readonly from: string; readonly through: string } }
  | { readonly kind: 'unavailable'; readonly signalId: string; readonly barEnd: string }

/** Resolves exact historical focus without choosing a nearby Bar or touching a performance window. */
export function resolveNewowReferenceLocate(
  trade: NewowReferenceTrade,
  chart: NewowProductSectionResponse<'chart'> | null,
): NewowReferenceLocate {
  const signalId = trade.entry_signal_id
  const barEnd = trade.entry_bar_end
  const exact = chart?.value?.actions.some((action) => action.signal_id === signalId && action.bar_end === barEnd) ?? false
  if (exact) return { kind: 'loaded', signalId, barEnd }
  const targetBarLoaded = chart?.value?.bars.some((bar) => bar.bar_end === barEnd) ?? false
  if (targetBarLoaded) return { kind: 'unavailable', signalId, barEnd }
  return {
    kind: 'request_display_window', signalId, barEnd,
    displayWindow: { from: trade.entry_trading_day, through: trade.entry_trading_day },
  }
}

export interface NewowExplanationPanelViewModel {
  readonly contextAsOf: string
  readonly contextRows: ReadonlyArray<{
    readonly frequency: string
    readonly barEnd: string
    readonly state: string
    readonly reason: string
  }>
  readonly sourceRows: ReadonlyArray<{
    readonly role: string
    readonly frequency: string
    readonly barEnd: string
    readonly formulas: string
    readonly evidence: string
    readonly reason: string
  }>
  readonly composite: {
    readonly positionRange: string
    readonly direction: string
    readonly directionPoints: string
    readonly certainty: string
    readonly volatility: string
    readonly firstActionToken: string
    readonly firstActionDetail: string
    readonly evidenceReason: string
  }
  readonly targetReason: string
}

/** Projects source-bound explanation facts and keeps unavailable evidence explicit. */
export function buildNewowExplanationPanelViewModel(
  response: NewowProductSectionResponse<'explanation'>,
): NewowExplanationPanelViewModel {
  if (response.value === null) throw new Error('Newow explanation value is unavailable')
  const value = response.value
  const composite = value.composite.value
  return {
    contextAsOf: value.context.as_of,
    contextRows: [value.context.weekly, value.context.daily, value.context.hourly].map((slot) => ({
      frequency: slot.frequency,
      barEnd: slot.bar_end ?? '—',
      state: slot.main_state ?? slot.availability.status,
      reason: slot.availability.reason_code ?? slot.confirmation_status.reason_code ?? '—',
    })),
    sourceRows: value.sources.map((source) => ({
      role: source.role,
      frequency: source.frequency ?? '—',
      barEnd: source.bar_end ?? '—',
      formulas: source.formula_versions.length === 0 ? '—' : source.formula_versions.join(' / '),
      evidence: source.status,
      reason: source.reason_code ?? '—',
    })),
    composite: {
      positionRange: composite?.decision.position_range ?? '—',
      direction: composite?.direction.token ?? '—',
      directionPoints: composite === null ? '—' : String(composite.direction.certainty_points),
      certainty: composite === null ? '—' : String(composite.certainty.total),
      volatility: composite?.volatility === null || composite === null
        ? '—'
        : `${formatDecimalString(composite.volatility.value_pct)}% · ${composite.volatility.level} · ${composite.volatility.is_wilder_atr ? 'Wilder ATR' : '非 Wilder ATR'}`,
      firstActionToken: composite?.first_action.rule_token ?? '—',
      firstActionDetail: composite?.first_action.page_detail ?? '—',
      evidenceReason: composite === null ? value.composite.reason_code ?? 'EVIDENCE_UNAVAILABLE' : '—',
    },
    targetReason: value.target_absorb.value === null ? value.target_absorb.reason_code ?? 'EVIDENCE_UNAVAILABLE' : '—',
  }
}

export interface NewowComparatorPanelViewModel {
  readonly label: '五窗口页面比较器（独立理论结果）'
  readonly windows: ReadonlyArray<{
    readonly window: number
    readonly returnText: string
    readonly drawdownText: string
    readonly winRateText: string
    readonly syntheticTerminal: boolean
  }>
  readonly syntheticTerminalIsReferenceExit: false
  readonly disclosure: string
  readonly reason: string
}

/** Projects the isolated in-sample comparator without feeding its result into strategy selection. */
export function buildNewowComparatorPanelViewModel(
  response: NewowProductSectionResponse<'comparator'>,
): NewowComparatorPanelViewModel {
  const result = response.value?.result ?? null
  const value = result?.value ?? null
  const byWindow = new Map(value?.segments.flatMap((segment) => segment.results).map((item) => [item.window, item]) ?? [])
  const candidateWindows = value?.candidate_windows ?? []
  return {
    label: '五窗口页面比较器（独立理论结果）',
    windows: candidateWindows.map((window) => {
      const item = byWindow.get(window)
      return {
        window,
        returnText: percentageText(item?.page_display.cumulative_return_pct ?? null),
        drawdownText: percentageText(item?.page_display.max_drawdown_pct ?? null),
        winRateText: percentageText(item?.page_display.win_rate_pct ?? null),
        syntheticTerminal: item?.force_closed_at_end === true || item?.trades.some((trade) => trade.synthetic_terminal) === true,
      }
    }),
    syntheticTerminalIsReferenceExit: false,
    disclosure: '样本内、零成本、样本末理论平仓仅属于比较器；不改变 ReferenceTrade 的 OPEN/CLEAR，不新增 CLEAR，也不自动选择策略参数。',
    reason: value === null ? result?.reason_code ?? response.status.reason_code ?? 'EVIDENCE_UNAVAILABLE' : '—',
  }
}

export interface NewowPanelRenderState {
  readonly showValue: boolean
  readonly message: string
  readonly staleAt: string | null
}

export function resolveNewowPanelRenderState(
  lifecycle: NewowResourceLifecycle | string,
  response: Pick<NewowProductSectionResponse, 'meta'> | null,
  error: string | null,
): NewowPanelRenderState {
  if (lifecycle === 'stale' && response !== null) return {
    showValue: true,
    message: `刷新失败${error === null ? '' : `（${error}）`}；以下为同一身份上次成功的 stale 数值。`,
    staleAt: response.meta.read_at,
  }
  if (lifecycle === 'loading') return {
    showValue: response !== null,
    message: response === null ? '正在加载…' : '正在刷新；以下为同一身份上次成功的数值。',
    staleAt: null,
  }
  if (lifecycle === 'ready' || lifecycle === 'warming' || lifecycle === 'evidence_required') return {
    showValue: response !== null,
    message: lifecycle === 'ready' ? '' : `当前资源状态：${lifecycle}。`,
    staleAt: null,
  }
  if (lifecycle === 'not_requested') return { showValue: false, message: '尚未请求。', staleAt: null }
  if (lifecycle === 'input_conflict') return {
    showValue: false,
    message: `DATA_CONFLICT${error === null ? '' : `（${error}）`}：冲突事实已清空，不能继续展示旧数值。`,
    staleAt: null,
  }
  return {
    showValue: false,
    message: `加载失败${error === null ? '' : `（${error}）`}，没有可显示的已验证数值。`,
    staleAt: null,
  }
}

function referenceRow(
  trade: NewowReferenceTrade,
  loadedHints: ReadonlyMap<string, NewowProductHint>,
): NewowReferenceRowViewModel {
  const initial = trade.statistics_membership === 'initial_before_window'
  const category: NewowReferenceCategory = initial
    ? 'initial'
    : trade.status === 'CLOSED'
      ? 'closed'
      : trade.status === 'OPEN'
        ? 'open'
        : 'interrupted'
  const percentage = initial
    ? percentageText(trade.reference_return_pct, '（期初已有，不计入窗口统计）')
    : trade.status === 'CLOSED'
      ? percentageText(trade.reference_return_pct)
      : trade.status === 'ROLLOVER_INTERRUPTED'
        ? percentageText(trade.mark_change_pct, '（中断浮动）')
        : percentageText(trade.mark_change_pct, '（当前浮动）')
  return {
    id: trade.reference_trade_id,
    trade,
    category,
    statusText: initial ? '期初已有' : trade.status,
    returnText: percentage,
    valuationText: trade.mark_bar_end === null || trade.mark_reference_price === null
      ? `不可用${trade.interruption_reason === null ? '' : `（${trade.interruption_reason}）`}`
      : `${trade.mark_bar_end} · ${trade.mark_reference_price}`,
    hints: trade.hint_ids.map((id) => {
      const fact = loadedHints.get(id) ?? null
      return fact === null
        ? { id, availability: 'unavailable', text: '未在已加载图表事实中找到，不能按邻近日期或当前上下文推断。', fact }
        : { id, availability: 'loaded', text: `${fact.kind} · ${fact.bar_end} · 同 Bar 提示（顺序未推断）`, fact }
    }),
  }
}

function percentageText(value: string | null, suffix = ''): string {
  return value === null ? '—' : `${formatDecimalString(value)}%${suffix}`
}

/** Format the server Decimal lexeme without converting it to a binary number. */
export function formatDecimalString(value: string | null, fractionDigits?: number): string {
  if (value === null) return '—'
  const expanded = expandExponent(value)
  const sign = expanded.startsWith('-') ? '-' : expanded.startsWith('+') ? '+' : ''
  const unsigned = sign ? expanded.slice(1) : expanded
  let [whole, fraction = ''] = unsigned.split('.')
  whole = whole || '0'
  if (fractionDigits !== undefined) {
    if (!Number.isInteger(fractionDigits) || fractionDigits < 0 || fractionDigits > 100) throw new Error('fractionDigits is invalid')
    fraction = fraction.slice(0, fractionDigits).padEnd(fractionDigits, '0')
  }
  const grouped = whole.replace(/\B(?=(\d{3})+(?!\d))/g, ',')
  return `${sign}${grouped}${fraction.length ? `.${fraction}` : ''}`
}

function expandExponent(value: string): string {
  const match = /^([+-]?)(\d*\.?\d*)[eE]([+-]?\d+)$/.exec(value)
  if (match === null) return value
  const sign = match[1]!
  const mantissa = match[2]!
  const exponent = Number(match[3])
  if (!Number.isSafeInteger(exponent) || Math.abs(exponent) > 10000) throw new Error('Decimal exponent is invalid')
  const [whole = '', fraction = ''] = mantissa.split('.')
  const digits = `${whole}${fraction}` || '0'
  const point = whole.length + exponent
  if (point <= 0) return `${sign}0.${'0'.repeat(-point)}${digits}`
  if (point >= digits.length) return `${sign}${digits}${'0'.repeat(point - digits.length)}`
  return `${sign}${digits.slice(0, point)}.${digits.slice(point)}`
}
