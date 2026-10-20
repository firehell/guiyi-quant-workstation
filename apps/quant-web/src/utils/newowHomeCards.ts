import type { PriceProvenance } from './newowPriceSources.ts'
import { comparePositiveDecimalText } from './marketDisplay.ts'
import { previewInstant } from './candidatePreviewInstant.ts'
import { newowReferencePrice } from './newowPagePresentation.ts'

export type HomeStrategy = 'trend' | 'oscillation'
export type HomePeriod = '1d' | '1w'
export type HomeState = 'BUILD' | 'HOLD' | 'CLEAR' | 'FLAT'
export interface HomePeriodFact {
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
  row_hints?: { status: string; bar_end: string; physical_contract: string; calculation_segment_id: string; page_parity: boolean; executable: boolean; items: Array<{ kind: 'caution' | 'reduce'; event_bar_end?: string; tentative?: boolean; confirmed_day?: string | null; peak_day?: string; event_day: string; j_value?: string; reference_price?: string; formula_version: string }> } | null
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
export interface CardDelivery { card: HomeCard | null; loading: boolean; stale: boolean; failed: boolean; savedAt?: string }

/** Fresh session aliases include the complete accepted overview authority. */
export function homeCardSessionKey(products: readonly string[], authority: string) { return `home:${products.join(',')}:${authority}` }

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

/** trendMap is an independent source fact; alignment cannot stand in for it. */
export function homeTrendDisplay() { return { label: '独立趋势来源未确认', tone: 'pending' } as const }

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

export function homeDeliveryNotice(delivery?: CardDelivery) {
  if (delivery?.stale) return delivery.loading ? delivery.savedAt ? '本地策略快照，正在重新验证' : '策略刷新中，保留上次快照' : delivery.failed ? '策略刷新失败，保留上次快照' : '本地策略快照，等待重新验证'
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

/** Two workers; late/cancelled generations cannot replace a newer snapshot. */
export function createHomeCardLoader(fetch: (products: string[], signal: AbortSignal) => Promise<HomeCardsResponse>, publish: (items: Record<string, CardDelivery>) => void, cached?: (product: string) => HomeCardsResponse | undefined) {
  let generation = 0
  let controller: AbortController | null = null
  let items: Record<string, CardDelivery> = {}
  const revisions = new Map<string, number>()
  type Queue = { generation: number; signal: AbortSignal; products: string[]; workers: Set<Promise<void>> }
  let queue: Queue | null = null
  function addProducts(products: readonly string[]) {
    if (!queue) return
    for (const product of products) {
      if (items[product]) continue
      const snapshot = cached?.(product), card = snapshot?.items.find(item => item.product === product)
      const validated = card && !snapshot?.restored
      items[product] = card ? { card, loading: !validated, stale: !validated, failed: false, savedAt: snapshot?.requested_at } : { card: null, loading: true, stale: false, failed: false }
      if (!card || !validated) queue.products.push(product)
    }
    publish({ ...items })
  }
  function startWorkers(owner: Queue) {
    while (owner.products.length && owner.workers.size < 2) {
      const worker = (async () => {
        while (owner.products.length && owner.generation === generation && !owner.signal.aborted) {
          const product = owner.products.shift()!
          const revision = (revisions.get(product) ?? 0) + 1
          revisions.set(product, revision)
          try {
            const response = normalizeHomeCards(await fetch([product], owner.signal), [product])
            if (owner.generation !== generation || owner.signal.aborted) return
            if (revisions.get(product) !== revision) continue
            items[product] = { card: response.items[0]!, loading: false, stale: false, failed: false }
          } catch {
            if (owner.generation !== generation || owner.signal.aborted) return
            if (revisions.get(product) !== revision) continue
            items[product] = { card: items[product]?.card ?? null, loading: false, stale: Boolean(items[product]?.card), failed: true }
          }
          publish({ ...items })
        }
      })().finally(() => owner.workers.delete(worker))
      owner.workers.add(worker)
    }
  }
  return {
    async load(products: readonly string[]) {
      const current = ++generation
      controller?.abort()
      controller = new AbortController()
      const previous = items
      items = {}
      queue = { generation: current, signal: controller.signal, products: [], workers: new Set() }
      addProducts(products)
      for (const product of products) {
        if (items[product]?.loading && previous[product]?.card) items[product] = { ...items[product]!, card: previous[product]!.card, stale: true }
      }
      publish({ ...items })
      startWorkers(queue)
      await Promise.all([...queue.workers])
    },
    admit(products: readonly string[]) {
      if (!queue || queue.signal.aborted) return
      const newlyAdmitted = products.filter(product => !items[product])
      addProducts(products)
      // A newly visible row takes the next free slot; active reads finish.
      queue.products = [...newlyAdmitted.filter(product => items[product]?.loading), ...queue.products.filter(product => !newlyAdmitted.includes(product))]
      startWorkers(queue)
    },
    async reloadProduct(product: string) {
      const current = generation, signal = controller?.signal
      if (!signal || signal.aborted || !items[product]) return
      const revision = (revisions.get(product) ?? 0) + 1
      revisions.set(product, revision)
      items[product] = { card: items[product]!.card, loading: true, stale: Boolean(items[product]!.card), failed: false }
      publish({ ...items })
      try {
        const response = normalizeHomeCards(await fetch([product], signal), [product])
        if (current !== generation || signal.aborted || revisions.get(product) !== revision) return
        items[product] = { card: response.items[0]!, loading: false, stale: false, failed: false }
      } catch {
        if (current !== generation || signal.aborted || revisions.get(product) !== revision) return
        items[product] = { card: items[product]!.card, loading: false, stale: Boolean(items[product]!.card), failed: true }
      }
      publish({ ...items })
    },
    dispose() { ++generation; controller?.abort() },
  }
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
  if (day?.status !== 'ready' || !day.bar_end || !day.physical_contract || !day.calculation_segment_id || !hints || hints.status !== 'ready' || hints.page_parity !== true || hints.executable !== false || hints.bar_end !== day.bar_end || hints.physical_contract !== day.physical_contract || hints.calculation_segment_id !== day.calculation_segment_id || !Array.isArray(hints.items)) return []
  return hints.items.filter(item => item.formula_version && /^\d{4}-\d{2}-\d{2}$/.test(item.event_day) && item.event_day <= day.bar_end!.slice(0, 10) && (item.kind === 'caution' ? /^\d{4}-\d{2}-\d{2}$/.test(item.peak_day ?? '') && item.peak_day! <= item.event_day : item.kind === 'reduce' && Number.isFinite(Number(item.j_value)) && Number(item.reference_price) > 0)).map(item => ({
    label: item.kind === 'caution' ? '小心' : '减仓',
    focusBarEnd: item.kind === 'caution' ? item.event_bar_end : undefined,
    title: item.kind === 'caution' ? item.tentative ? `当天暂定峰（${item.event_day}），尚未回落5%确认 · 回看会变化，非交易信号` : `波峰（${item.peak_day}）事件 ${item.event_day}${item.confirmed_day ? ` · 确认于 ${item.confirmed_day}` : " · 历史回看"} · 页面参考提示` : `J值（${Number(item.j_value).toFixed(1)}）自高位回落 · ${item.event_day} · 参考价 ${newowReferencePrice(item.reference_price)} · 页面参考提示`,
  }))
}
