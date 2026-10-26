import { CAUTION_DISPLAY_VERSION, normalizeCautionDisplay, cautionDisplayTitle } from './newowCautionDisplay.ts'
import type { NewowCautionEvent } from '../types/newowProduct.ts'
import type { PriceProvenance } from './newowPriceSources.ts'
import { comparePositiveDecimalText } from './marketDisplay.ts'
import { previewInstant } from './candidatePreviewInstant.ts'
import { newowReferencePrice } from './newowPagePresentation.ts'

export type HomeStrategy = 'trend' | 'oscillation'
export type HomePeriod = '1d' | '1w'
export type HomeState = 'BUILD' | 'HOLD' | 'CLEAR' | 'FLAT'
export interface HomeIndependentTrend {
  status: 'ready' | 'warming' | 'unavailable'
  direction: 'bull' | 'bear' | null
  formula_version: string
  frequency: '1d'
  bar_end: string
  physical_contract: string
  segment_id: string
  calculation_segment_id: string
  input_sha256: string | null
  parent_input_sha256: string
  close: string | null
  ma60: string | null
  sample_count: number
  approximate: true
  page_parity: false
  executable: false
}
export interface HomePeriodFact {
  independent_trend?: HomeIndependentTrend | null
  status: 'ready' | 'warming' | 'unavailable'
  state: HomeState | null
  reason_code?: string | null
  as_of?: string
  bar_end?: string
  physical_contract?: string
  segment_id?: string
  calculation_segment_id?: string
  source_identity?: string
  input_sha256?: string
  snapshot_context?: unknown
  data_revision_identity?: unknown
  snapshot_token?: string
  formula_versions?: string[]
  freshness?: string
  reference_current?: string | null
  reference_cost?: string | null
  entry_signal_id?: string | null
  price_sources?: { target: PriceProvenance | null; absorb: PriceProvenance | null } | null
  price_input_sha256?: string
  price_formula_version?: string
  target?: string | null
  absorb?: string | null
  target_space_percent?: string | null
  absorb_space_percent?: string | null
  main_force_control?: { status: string; label: string | null; formula_version: string; bar_end: string; physical_contract: string; calculation_segment_id: string; page_parity: boolean; executable: boolean }
  row_hints?: { display_policy_version?: string; status: string; bar_end: string; physical_contract: string; calculation_segment_id: string; page_parity: boolean; executable: boolean; items: Array<{ kind: 'caution' | 'reduce'; event_bar_end?: string; tentative?: boolean; confirmed_day?: string | null; peak_day?: string; event_day: string; j_value?: string; reference_price?: string; formula_version: string } & Partial<Omit<NewowCautionEvent, 'formula_version'>>> } | null
  page_performance?: { status: string; reason_code?: string; version?: string; strategy?: HomeStrategy; frequency?: HomePeriod; as_of?: string; input_sha256?: string; source_evidence_sha256?: string | null; since?: string | null; through?: string | null; cum_return_percent?: string; trade_count?: number; page_parity?: boolean; executable?: boolean }
  display_as_of?: string
  display_projection_version?: 'newow_home_display_v1'
  current_event?: { kind: 'BUILD' | 'CLEAR'; bar_end: string; signal_id: string } | null
  guard_ma10?: string | null
  recent_action?: { kind: 'BUILD' | 'CLEAR'; bar_end: string; signal_id: string } | null
  page_parity?: boolean
  executable?: boolean
}
export interface HomeCard { product: string; strategies: Record<HomeStrategy, Record<HomePeriod, HomePeriodFact>> }
export interface HomeCardsResponse { schema_version: 'newow_home_cards_v2'; requested_at: string; items: HomeCard[]; restored?: boolean }
export interface CardDelivery { card: HomeCard | null; loading: boolean; stale: boolean; failed: boolean; savedAt?: string; projectionStatus?: import('./newowHomeProjection.ts').ProjectionStatus }

export const homeStateLabels = { BUILD: '建仓', HOLD: '持有', CLEAR: '清仓', FLAT: '空仓' } as const
export const homeStateIcons = { BUILD: '▲', HOLD: '✓', CLEAR: '↘', FLAT: '○' } as const

/** Presentation of the explicit daily state, never a new strategy calculation. */
export function homeReferenceDisplay(fact?: HomePeriodFact) {
  const target = fact?.status === 'ready' && (fact.state === 'BUILD' || fact.state === 'HOLD')
  const absorb = fact?.status === 'ready' && (fact.state === 'CLEAR' || fact.state === 'FLAT')
  return { label: target ? '目标' : absorb ? '吸筹' : '目标/吸筹', text: newowReferencePrice(target ? fact?.target : absorb ? fact?.absorb : null).replace(/^—$/, '--') }
}

export function homePeriodDisplay(fact?: HomePeriodFact) {
  if (fact?.status === 'ready' && fact.state) return { label: homeStateLabels[fact.state], icon: homeStateIcons[fact.state], tone: fact.state.toLowerCase() }
  return { label: fact?.status === 'warming' ? '预热中' : fact ? '不可用' : '加载中', icon: '—', tone: 'pending' }
}

export function homePeriodReason(fact?: HomePeriodFact): string | null {
  const code = fact?.reason_code
  if (!code) return null
  if (code.includes('CONFLICT') || code.includes('MISMATCH') || code.includes('IDENTITY_INVALID')) return '数据或快照身份冲突，等待核对'
  if (code === 'NEWOW_WEEKLY_STALE') return '周线发布时点待确认'
  if (code.includes('CANCELLED')) return '读取已中断，可刷新重试'
  return fact?.status === 'warming' ? '指标输入尚未完成预热' : '所需历史或来源事实暂不可用'
}

/** Day/week state alignment only. It does not infer a trend from price or scores. */
export function homeDirectionDisplay(day?: HomePeriodFact, week?: HomePeriodFact) {
  const identified = (fact?: HomePeriodFact): fact is HomePeriodFact & { state: HomeState } => Boolean(fact?.status === 'ready' && fact.state && fact.physical_contract && fact.segment_id && fact.calculation_segment_id && fact.input_sha256 && fact.formula_versions?.length)
  if (!identified(day) || !identified(week)) return { label: '待确认', tone: 'pending' }
  const up = (state: HomeState) => state === 'BUILD' || state === 'HOLD'
  if (up(day.state) !== up(week.state)) return { label: '日周分歧', tone: 'mixed' }
  return up(day.state) ? { label: '日周向上', tone: 'up' } : { label: '日周向下', tone: 'down' }
}

/** Display the owner's accepted approximation; never derive direction from live quotes. */
export function homeTrendDisplay(day?: HomePeriodFact, delivery?: Pick<CardDelivery, 'stale' | 'failed' | 'projectionStatus'>): {label: string; title: string; tone: 'up' | 'down' | 'pending'} {
  const pending = {label:'趋势来源待确认', title:'趋势待重建 · MA60近似规则', tone:'pending' as const}
  const value = day?.independent_trend
  if (!value || value.formula_version !== 'guiyi_home_close_ma60_v1' || value.frequency !== '1d'
    || value.approximate !== true || value.page_parity !== false || value.executable !== false
    || !value.input_sha256 || value.parent_input_sha256 !== day?.input_sha256
    || !value.physical_contract || value.physical_contract !== day.physical_contract
    || !value.segment_id || value.segment_id !== day.segment_id
    || !value.calculation_segment_id || value.calculation_segment_id !== day.calculation_segment_id
    || !value.bar_end || value.bar_end !== day.bar_end || previewInstant(value.bar_end) === null) return pending
  if (value.status === 'warming') return {label:'趋势预热中',title:`MA60近似 · 已完成日线 ${value.sample_count}/60 根`,tone:'pending'}
  if (value.status !== 'ready' || value.sample_count !== 60 || !['bull','bear'].includes(value.direction ?? '')
    || comparePositiveDecimalText(value.close, value.ma60) === null) return pending
  const stale = delivery?.stale || delivery?.failed || (delivery?.projectionStatus && delivery.projectionStatus !== 'ready')
  const label = `趋势向${value.direction === 'bull' ? '上' : '下'}（MA60近似）`
  return {label, tone:value.direction === 'bull' ? 'up' : 'down',
    title:`${stale ? '历史结果 · ' : ''}${label} · 收盘价与60日均线比较 · 截至 ${value.bar_end} · ${value.physical_contract} · 非牛哇原公式`}
}

const identifiedHomeFact = (fact?: HomePeriodFact): fact is HomePeriodFact & { state: HomeState } => Boolean(
  fact?.status === 'ready' && fact.state && fact.physical_contract && fact.segment_id && fact.calculation_segment_id && fact.input_sha256 && fact.formula_versions?.length
  && fact.page_parity === true && fact.executable === false && fact.display_projection_version === 'newow_home_display_v1'
  && fact.as_of && previewInstant(fact.as_of) !== null && fact.bar_end && previewInstant(fact.bar_end) !== null
  && fact.display_as_of && previewInstant(fact.display_as_of) !== null
  && previewInstant(fact.bar_end)! <= previewInstant(fact.as_of)! && previewInstant(fact.as_of)! <= previewInstant(fact.display_as_of)!
  && fact.current_event !== undefined)

/** Public buildCard precedence, applied only to an authenticated display projection. */
export function homeCompositeDisplay(day?: HomePeriodFact, week?: HomePeriodFact) {
  const reference = homeReferenceDisplay(day)
  const unavailable = { state: null, label: '综合状态不可用', reference, reason: '日周展示事实、截止时间或合约身份不完整' } as const
  if (!identifiedHomeFact(day) || !identifiedHomeFact(week) || previewInstant(day.display_as_of!) !== previewInstant(week.display_as_of!) || day.physical_contract !== week.physical_contract) return unavailable
  for (const fact of [day, week]) {
    const event = fact.current_event
    if (event && (!['BUILD', 'CLEAR'].includes(event.kind) || !event.signal_id || previewInstant(event.bar_end) === null || previewInstant(event.bar_end) !== previewInstant(fact.bar_end!))) return unavailable
  }
  let state: HomeState = day.state === 'CLEAR' || week.state === 'CLEAR' ? 'CLEAR'
    : week.state === 'BUILD' || week.state === 'HOLD' ? week.state
    : day.state === 'BUILD' || day.state === 'HOLD' ? day.state : 'FLAT'
  const cross = day.current_event?.kind
  const comparison = comparePositiveDecimalText(day.reference_current, day.guard_ma10)
  const dayValid = cross === 'BUILD' ? (comparison === null ? day.state !== 'FLAT' : comparison >= 0)
    : cross === 'CLEAR' ? (comparison === null ? day.state !== 'HOLD' : comparison <= 0) : false
  if (cross && dayValid) state = cross
  else if (week.current_event) state = week.current_event.kind
  // Frozen source contradiction guard runs after weekly event override too.
  if (day.state === 'HOLD' && cross === 'BUILD' && !dayValid) state = 'HOLD'
  return { state, label: homeStateLabels[state], reference, reason: '' }
}

/** Text and layout only: consume the existing authenticated composite and prices. */
export function homeCardPresentation(day?: HomePeriodFact, week?: HomePeriodFact) {
  const { state } = homeCompositeDisplay(day, week)
  const price = (value?: string | null) => newowReferencePrice(value).replace(/^—$/, '--')
  if (!state) return { state, prefix:'日周策略摘要', price:'--', suffix:'', signal:'待确认', glyph:'', context:'日周状态待确认，等待完整数据', stageIndex:-1 }
  const weeklyLead = week?.state === 'BUILD' || week?.state === 'HOLD'
  const target = price(day?.target), absorb = price(day?.absorb)
  const goal = target === '--' ? '日线目标价待确认' : `${target}（日线目标价）`
  if (state === 'BUILD') {
    const cost = day?.state === 'BUILD' || day?.state === 'HOLD' ? day.reference_cost
      : weeklyLead ? week?.reference_cost : null
    return { state, prefix:'预估当前', price:price(cost ?? day?.absorb), suffix:'附近可以买入', signal:'买入信号', glyph:'▲',
      context:weeklyLead ? (day?.state === 'BUILD' || day?.state === 'HOLD' ? `日周共振买入，目标看${goal}` : `周线买入（日线未确认），目标看${goal}`) : `日线买入（周线未确认），先反弹到${goal}`, stageIndex:1 }
  }
  if (state === 'HOLD') return { state, prefix:'当前持股，目标看', price:target, suffix:'', signal:'持股信号', glyph:'✓',
    context:weeklyLead ? `周线持股，目标看${goal}` : `日线持股（周线未确认），目标看${goal}`, stageIndex:2 }
  if (state === 'CLEAR') return { state, prefix:'当前', price:price(day?.reference_current), suffix:'已出现卖出信号', signal:'卖出信号', glyph:'▼',
    context:`${day?.state === 'CLEAR' || day?.current_event?.kind === 'CLEAR' ? '日线' : '周线'}卖出，等待新的买入信号`, stageIndex:3 }
  return { state, prefix:'预估当前', price:absorb, suffix:'附近可以关注', signal:'空仓信号', glyph:'×',
    context:absorb === '--' ? '日周空仓，等待买入信号；日线吸筹价待确认' : `日周空仓，等待买入信号；关注${absorb}（日线吸筹价）`, stageIndex:0 }
}

export function homeDeliveryNotice(delivery?: CardDelivery) {
  if (delivery?.projectionStatus === 'missing') return delivery.card ? '摘要待重建，保留历史快照' : '计算中… 尚无已发布摘要'
  if (delivery?.projectionStatus === 'updating') return delivery.card ? '摘要更新中，保留上次结果' : '计算中…'
  if (delivery?.projectionStatus === 'failed') return delivery.card ? '摘要更新失败，保留上次结果' : '摘要计算失败'
  if (delivery?.projectionStatus === 'stale' && !delivery.loading) return '历史策略摘要，等待数据更新'

  if (delivery?.stale) return delivery.loading ? delivery.savedAt ? '策略历史快照，正在重新验证' : '策略刷新中，保留上次快照' : delivery.failed ? '策略刷新失败，保留上次快照' : '策略历史快照，等待重新验证'
  if (delivery?.failed) return '策略读取失败，可刷新重试'
  return delivery?.loading || !delivery ? '策略读取中' : null
}

export function normalizeHomeCards(value: unknown, products: readonly string[]): HomeCardsResponse {
  const response = value as HomeCardsResponse
  if (response?.schema_version !== 'newow_home_cards_v2' || !Array.isArray(response.items) || response.items.length !== products.length || !Number.isFinite(Date.parse(response.requested_at))) throw new Error('INVALID_HOME_CARDS')
  const seen = new Set<string>()
  for (const item of response.items) {
    if (!products.includes(item.product) || seen.has(item.product)) throw new Error('INVALID_HOME_CARDS')
    seen.add(item.product)
    for (const strategy of ['trend', 'oscillation'] as const) for (const period of ['1d', '1w'] as const) {
      const fact = item.strategies?.[strategy]?.[period]
      if (!fact || !['ready', 'warming', 'unavailable'].includes(fact.status)) throw new Error('INVALID_HOME_CARDS')
      if (fact.status === 'ready' && (!['BUILD', 'HOLD', 'CLEAR', 'FLAT'].includes(fact.state ?? '') || !fact.physical_contract || !fact.segment_id || !fact.calculation_segment_id || !fact.input_sha256 || !fact.formula_versions?.length || !Number.isFinite(Date.parse(fact.as_of ?? '')) || !Number.isFinite(Date.parse(fact.bar_end ?? '')) || fact.page_parity !== true || fact.executable !== false)) throw new Error('INVALID_HOME_CARDS')
      for (const key of ['target', 'absorb', 'reference_cost', 'reference_current', 'target_space_percent', 'absorb_space_percent', 'guard_ma10'] as const) if (fact[key] != null && (typeof fact[key] !== 'string' || !Number.isFinite(Number(fact[key])))) throw new Error('INVALID_HOME_CARDS')
      const performance = fact.page_performance
      if (performance?.status === 'ready' && (!performance.version || !performance.input_sha256 || performance.frequency !== '1d' || performance.strategy !== strategy || performance.as_of !== fact.as_of || performance.page_parity !== true || performance.executable !== false || !Number.isInteger(performance.trade_count) || performance.trade_count! < 0 || typeof performance.cum_return_percent !== 'string' || !Number.isFinite(Number(performance.cum_return_percent)))) throw new Error('INVALID_HOME_PERFORMANCE')
      const control = fact.main_force_control
      if (control?.status === 'ready' && (!control.formula_version || !['无庄控盘','开始控盘','有庄控盘','高度控盘','主力出货','高控+出货'].includes(control.label ?? '') || control.bar_end !== fact.bar_end || control.physical_contract !== fact.physical_contract || control.calculation_segment_id !== fact.calculation_segment_id || control.page_parity !== true || control.executable !== false)) throw new Error('INVALID_HOME_CONTROL')
      if (fact.status !== 'ready' && fact.state !== null) throw new Error('INVALID_HOME_CARDS')
    }
  }
  return response
}

/** Reload on overview facts, not the wall-clock time of an identical readback. */
export function homeCardsReloadIdentity(overview: { target_as_of: string; items: readonly { symbol: string }[] } | null | undefined) {
  return overview ? JSON.stringify([overview.target_as_of, [...overview.items].sort((a, b) => a.symbol.localeCompare(b.symbol))]) : ''
}

/** Presentation only: space uses the confirmed daily anchor, never live ticks. */
export function homeCardSpace(day?: HomePeriodFact) {
  const target = homeReferenceDisplay(day).label === '目标'
  const value = target ? day?.target_space_percent : day?.absorb_space_percent
  if (day?.status !== 'ready' || value == null) return { label: '空间待确认', value: null, target }
  return { label: target ? '预计上涨空间' : '预计下跌空间', value, target }
}

export function homeControlLabel(day?: HomePeriodFact) {
  const control = day?.main_force_control
  return day?.status === 'ready' && control?.status === 'ready' && control.page_parity === true && control.executable === false
    && control.physical_contract === day.physical_contract && control.calculation_segment_id === day.calculation_segment_id && control.bar_end === day.bar_end
    ? control.label ?? '控盘待确认' : '控盘待确认'
}

export function homePagePerformance(day: HomePeriodFact | undefined, strategy: HomeStrategy) {
  const value = day?.page_performance
  return value?.status === 'ready' && value.page_parity === true && value.executable === false && value.frequency === '1d' && value.strategy === strategy
    && value.version && value.input_sha256 && value.as_of === day?.as_of
    && Number.isInteger(value.trade_count) && value.trade_count! >= 0 && typeof value.cum_return_percent === 'string'
    ? value : null
}

export function homeRowHints(day?: HomePeriodFact) {
  const hints = day?.row_hints
  if (day?.status !== 'ready' || !day.bar_end || !day.physical_contract || !day.calculation_segment_id || !hints || hints.status !== 'ready' || hints.display_policy_version!==CAUTION_DISPLAY_VERSION || hints.page_parity !== false || hints.executable !== false || hints.bar_end !== day.bar_end || hints.physical_contract !== day.physical_contract || hints.calculation_segment_id !== day.calculation_segment_id || !Array.isArray(hints.items)) return []
  return hints.items.flatMap<{label: string; focusBarEnd?: string; title: string}>(item => {
    if (item.kind==='caution') {
      try {
        const {kind, event_day, event_bar_end, confirmed_day, ...wire}=item
        const e=normalizeCautionDisplay(wire)
        if (!e.home_visible || e.frequency!=='1d' || e.physical_contract!==day.physical_contract || e.segment_id!==day.segment_id || e.calculation_segment_id!==day.calculation_segment_id || Date.parse(e.as_of)!==Date.parse(day.bar_end!) || Date.parse(e.bar_end)!==Date.parse(event_bar_end??'') || !/^\d{4}-\d{2}-\d{2}$/.test(event_day)) return []
        return [{label:'小心',focusBarEnd:e.bar_end,title:cautionDisplayTitle(e)}]
      } catch { return [] }
    }
    if (item.kind!=='reduce' || !item.formula_version || !/^\d{4}-\d{2}-\d{2}$/.test(item.event_day) || !Number.isFinite(Number(item.j_value)) || Number(item.reference_price)<=0) return []
    return [{label:'减仓',focusBarEnd:undefined,title:`J值（${Number(item.j_value).toFixed(1)}）自高位回落 · ${item.event_day} · 参考价 ${newowReferencePrice(item.reference_price)} · 页面参考提示`}]
  })
}
