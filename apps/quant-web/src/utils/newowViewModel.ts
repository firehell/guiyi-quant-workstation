import type {
  DetailViewModel,
  MarketDetailDisclosureRow,
  MarketDetailDisclosureSection,
  MarketDetailFact,
  MarketDetailHeaderModel,
  MarketDetailHistoryItem,
  MarketDetailIdentity,
} from '../types/marketDetail.ts'
import type {
  NewowCupHandle,
  NewowCupState,
  NewowEscapeMarkerType,
  NewowMarker,
  NewowTrendDetailResponse,
} from '../types/newow.ts'

export interface NewowDetailViewModelInput {
  identity: MarketDetailIdentity
  header: MarketDetailHeaderModel
  data: NewowTrendDetailResponse | null
}

const D_PRIORITY: Readonly<Record<NewowEscapeMarkerType, number>> = {
  NEWOW_ESCAPE_D1: 0,
  NEWOW_ESCAPE_D2: 1,
  NEWOW_ESCAPE_D3: 2,
}

const SAME_FAMILY_MARKER_ORDER: Readonly<Record<string, number>> = {
  NEWOW_ESCAPE_D1: 0,
  NEWOW_ESCAPE_D2: 1,
  NEWOW_ESCAPE_D3: 2,
  CUP_HANDLE_READY: 0,
  CUP_HANDLE_BREAKOUT: 1,
  CUP_HANDLE_WEAKENED: 2,
  CUP_HANDLE_INVALIDATED: 3,
  CUP_HANDLE_EXPIRED: 4,
}

const CUP_STATE_LABEL: Readonly<Record<NewowCupState, string>> = {
  FORMING: '形成',
  READY: '就绪',
  BREAKOUT: '突破',
  WEAKENED: '走弱',
  INVALIDATED: '失效',
  EXPIRED: '过期',
}

/** Projects normalized, completed-only API facts without recreating Newow calculations. */
export function buildNewowDetailViewModel(input: NewowDetailViewModelInput): DetailViewModel {
  const data = snapshotForIdentity(input.data, input.identity)
  const facts = currentFacts(data)
  return {
    view: 'trend',
    identity: input.identity,
    asOf: data?.bars.at(-1)?.bar_end ?? null,
    semanticBanner: {
      text: '建仓、持有、清仓、空仓为趋势引擎状态，不代表实际账户持仓。牛哇页面复刻与 clean-room 研究结论分开显示；所有结果仅供研究观察。',
      tone: 'warning',
    },
    facts,
    disclosureSections: disclosures(data, input.header, facts),
    history: data === null ? [] : newowMarkerHistory(data),
    dataStatus: data === null
      ? 'unavailable'
      : input.header.freshness === 'fresh' ? 'ready'
        : input.header.freshness === 'stale' ? 'stale' : 'unavailable',
  }
}

/** Combines API marker families only; these entries are not AlertEvent or delivery facts. */
export function newowMarkerHistory(data: NewowTrendDetailResponse): MarketDetailHistoryItem[] {
  const contractByBarEnd = new Map(data.bars.map((bar) => [bar.bar_end, bar.physical_contract]))
  const entries: HistoryProjection[] = [
    ...data.trend_markers.map((marker) => historyProjection(marker, 0, contractByBarEnd)),
    ...data.escape_markers.map((marker) => historyProjection(marker, 1, contractByBarEnd)),
    ...data.cup_markers.map((marker) => historyProjection(marker, 2, contractByBarEnd)),
  ]
  entries.sort((left, right) => {
    const timeOrder = Date.parse(right.item.occurredAt) - Date.parse(left.item.occurredAt)
    if (timeOrder !== 0) return timeOrder
    if (left.familyOrder !== right.familyOrder) return left.familyOrder - right.familyOrder
    const typeOrder = markerTypeOrder(left.item.markerType) - markerTypeOrder(right.item.markerType)
    return typeOrder !== 0 ? typeOrder : lexical(left.item.id, right.item.id)
  })
  return entries.map(({ item }) => item)
}

interface HistoryProjection {
  familyOrder: number
  item: MarketDetailHistoryItem
}

function historyProjection(
  marker: NewowMarker,
  familyOrder: number,
  contractByBarEnd: ReadonlyMap<string, string>,
): HistoryProjection {
  return {
    familyOrder,
    item: {
      id: `newow-marker:${marker.marker_id}`,
      label: marker.label,
      occurredAt: marker.bar_end,
      source: 'newow',
      barEnd: marker.bar_end,
      contract: contractByBarEnd.get(marker.bar_end),
      markerType: marker.marker_type,
      formulaVersion: marker.formula_version,
    },
  }
}

function currentFacts(data: NewowTrendDetailResponse | null): DetailViewModel['facts'] {
  if (data === null) return unavailableFacts()
  const latestBar = data.bars.at(-1)
  const latestBand = data.trend_band.at(-1)

  const trendUnavailable = latestBar === undefined
    || latestBand === undefined
    || data.warnings.includes('NEWOW_TREND_WARMUP_INSUFFICIENT')
  const trendValue = trendUnavailable ? '不可用'
    : latestBand.transition === 'BUILD' ? '建仓'
      : latestBand.transition === 'CLEAR' ? '清仓'
        : latestBand.state === 'YELLOW' ? '持有'
          : latestBand.state === 'BLUE' ? '空仓' : '不可用'

  const escapeUnavailable = latestBar === undefined
    || data.warnings.includes('NEWOW_D123_WARMUP_INSUFFICIENT')
  const latestEscape = escapeUnavailable ? undefined : data.escape_markers
    .filter((marker) => marker.bar_end === latestBar.bar_end)
    .sort((left, right) => D_PRIORITY[left.marker_type] - D_PRIORITY[right.marker_type])[0]
  const escapeValue = escapeUnavailable
    ? '不可用'
    : latestEscape?.marker_type.replace('NEWOW_ESCAPE_', '') ?? '无'

  const cupUnavailable = latestBar === undefined
    || data.warnings.includes('NEWOW_CUP_WARMUP_INSUFFICIENT')
  const currentCup = cupUnavailable ? undefined : latestCup(data.cup_handles)
  const cupValue = cupUnavailable ? '不可用' : currentCup ? CUP_STATE_LABEL[currentCup.state] : '无'

  return [
    fact('trend-state', '当前趋势状态', trendValue, trendUnavailable ? 'unavailable' : trendTone(trendValue)),
    fact('d-risk', '当前 D1/D2/D3 风险', escapeValue, escapeUnavailable ? 'unavailable' : latestEscape ? 'warning' : 'default'),
    fact('cup-state', '当前杯柄状态', cupValue, cupUnavailable ? 'unavailable' : cupTone(currentCup)),
  ]
}

function unavailableFacts(): DetailViewModel['facts'] {
  return [
    fact('trend-state', '当前趋势状态', '不可用', 'unavailable'),
    fact('d-risk', '当前 D1/D2/D3 风险', '不可用', 'unavailable'),
    fact('cup-state', '当前杯柄状态', '不可用', 'unavailable'),
  ]
}

function fact(
  id: string,
  label: string,
  value: string,
  tone: MarketDetailFact['tone'],
): MarketDetailFact {
  return { id, label, value, tone, source: 'newow' }
}

function latestCup(handles: readonly NewowCupHandle[]): NewowCupHandle | undefined {
  return [...handles].sort((left, right) => {
    const timeOrder = Date.parse(right.state_changed_at) - Date.parse(left.state_changed_at)
    return timeOrder !== 0 ? timeOrder : lexical(left.candidate_id, right.candidate_id)
  })[0]
}

function disclosures(
  data: NewowTrendDetailResponse | null,
  header: MarketDetailHeaderModel,
  facts: DetailViewModel['facts'],
): readonly MarketDetailDisclosureSection[] {
  if (data === null) {
    return [{
      id: 'newow-unavailable', title: '趋势判断', summary: '趋势策略数据不可用',
      updatedAt: null, tone: 'unavailable',
      rows: [{ label: '当前状态', value: '不可用', source: 'newow' }],
    }]
  }
  const latestBar = data.bars.at(-1)
  const latestBand = data.trend_band.at(-1)
  const latestTransition = latestTrendTransition(data)
  const escapeUnavailable = data.warnings.includes('NEWOW_D123_WARMUP_INSUFFICIENT')
  const currentEscapeMarkers = latestBar === undefined || escapeUnavailable
    ? []
    : data.escape_markers
      .filter((marker) => marker.bar_end === latestBar.bar_end)
      .sort((left, right) => D_PRIORITY[left.marker_type] - D_PRIORITY[right.marker_type])
  const historicalEscape = latestEscapeMarker(data.escape_markers)
  const cupUnavailable = data.warnings.includes('NEWOW_CUP_WARMUP_INSUFFICIENT')
  const cup = cupUnavailable
    ? undefined : latestCup(data.cup_handles)
  const latestRollover = data.rollover_seams.at(-1)
  return [
    {
      id: 'newow-trend', title: '趋势判断', summary: facts[0].value,
      updatedAt: latestBar?.bar_end ?? null,
      tone: facts[0].tone === 'unavailable' ? 'unavailable' : 'default',
      rows: [
        { label: '当前策略状态', value: facts[0].value, source: 'newow' },
        { label: '当前趋势带', value: latestBand?.state ?? '不可用', source: 'newow' },
        { label: '最近转换', value: latestTransition?.transition ?? '无', source: 'newow' },
        { label: '转换时间', value: latestTransition?.bar_end ?? '无', source: 'newow' },
        { label: '当前物理合约', value: latestBar?.physical_contract ?? '不可用', source: 'newow' },
        { label: '分析截至 completed D1', value: latestBar?.bar_end ?? '不可用', source: 'newow' },
      ],
    },
    {
      id: 'newow-risk-shape', title: '风险与形态', summary: `${facts[1].value} · ${facts[2].value}`,
      updatedAt: latestBar?.bar_end ?? null,
      tone: facts[1].tone === 'unavailable' || facts[2].tone === 'unavailable' ? 'unavailable' : 'default',
      rows: [
        ...escapeDisclosureRows(escapeUnavailable, currentEscapeMarkers, historicalEscape, latestBar?.bar_end),
        ...cupDisclosureRows(cupUnavailable, cup),
      ],
    },
    {
      id: 'newow-channel', title: '目标价与吸纳价',
      summary: `${formatNumber(data.price_channel.display.target)} / ${formatNumber(data.price_channel.display.absorb)}`,
      updatedAt: latestBar?.bar_end ?? null,
      tone: data.price_channel.display.target === null ? 'unavailable' : 'default',
      rows: [
        { label: '页面目标价', value: formatNumber(data.price_channel.display.target), source: 'newow' },
        { label: '页面吸纳价', value: formatNumber(data.price_channel.display.absorb), source: 'newow' },
        { label: '目标周期', value: data.price_channel.display.target_period ?? '不可用', source: 'newow' },
        { label: '吸纳周期', value: data.price_channel.display.absorb_period ?? '不可用', source: 'newow' },
        { label: '目标分支', value: data.price_channel.display.target_branch_token, source: 'newow' },
        { label: '吸纳分支', value: data.price_channel.display.absorb_branch_token, source: 'newow' },
        { label: '日线 owner segments', value: jsonText(data.price_channel.daily.owner_segment_ids), source: 'newow' },
        { label: '周线 owner segments', value: jsonText(data.price_channel.weekly.owner_segment_ids), source: 'newow' },
        { label: '60m owner segments', value: jsonText(data.price_channel.sixty_minute.owner_segment_ids), source: 'newow' },
      ],
    },
    {
      id: 'newow-composite', title: '综合决策',
      summary: data.composite_page?.action_token ?? '不可用',
      updatedAt: data.diagnostic_facts.as_of,
      tone: data.composite_page === null ? 'unavailable' : 'warning',
      rows: [
        { label: '页面复刻动作', value: data.composite_page?.action_token ?? '不可用', source: 'newow' },
        { label: '页面复刻决策键', value: data.composite_page?.decision_key ?? '不可用', source: 'newow' },
        { label: '页面仓位区间', value: formatRange(data.composite_page?.position_range), source: 'newow' },
        { label: '页面确定性', value: data.composite_page ? String(data.composite_page.certainty.total) : '不可用', source: 'newow' },
        { label: '页面回放可信研究', value: '否（同 Bar 收盘，仅用于页面复刻）', source: 'newow' },
        { label: 'Clean-room 动作', value: data.composite_cleanroom?.action_token ?? '不可用', source: 'newow' },
        { label: 'Clean-room 决策键', value: data.composite_cleanroom?.decision_key ?? '不可用', source: 'newow' },
        { label: 'Clean-room 仓位区间', value: formatRange(data.composite_cleanroom?.position_range), source: 'newow' },
        { label: '差异原因', value: data.composite_cleanroom?.page_difference_reason ?? '无', source: 'newow' },
        { label: '页面不可达决策键', value: jsonText(data.composite_page?.unreachable_decision_keys ?? []), source: 'newow' },
      ],
    },
    {
      id: 'newow-first-action', title: '第一行动原则',
      summary: `${data.first_action_principle.level} · ${data.first_action_principle.rule_token}`,
      updatedAt: data.diagnostic_facts.as_of,
      tone: data.first_action_principle.level === 'violate' ? 'warning' : 'default',
      rows: [
        { label: '级别', value: data.first_action_principle.level, source: 'newow' },
        { label: '规则', value: data.first_action_principle.rule_token, source: 'newow' },
        { label: '事实 tokens', value: jsonText(data.first_action_principle.fact_tokens), source: 'newow' },
        { label: '与综合决策关系', value: '独立规则，不覆盖页面复刻或 clean-room 综合结论', source: 'newow' },
      ],
    },
    {
      id: 'newow-diagnostics', title: '诊断与解释',
      summary: `${data.diagnostic_tokens.length} 条诊断`,
      updatedAt: data.diagnostic_facts.as_of,
      tone: data.diagnostic_tokens.some((token) => token.severity === 'risk') ? 'warning' : 'default',
      rows: [
        { label: '趋势状态/持续', value: `${data.diagnostic_facts.trend_state} / ${data.diagnostic_facts.trend_duration_bars}`, source: 'newow' },
        { label: '周/日信号', value: `${data.diagnostic_facts.weekly_signal ?? '不可用'} / ${data.diagnostic_facts.daily_signal ?? '不可用'}`, source: 'newow' },
        { label: '震荡持有', value: booleanText(data.diagnostic_facts.oscillation_holding), source: 'newow' },
        { label: '主力控盘', value: data.diagnostic_facts.main_force_status ?? '不可用', source: 'newow' },
        { label: '主升浪', value: booleanText(data.diagnostic_facts.main_rise_active), source: 'newow' },
        { label: '杯柄状态', value: data.diagnostic_facts.cup_state ?? '不可用', source: 'newow' },
        { label: 'EMA20/位置', value: `${formatNumber(data.diagnostic_facts.ema20)} / ${data.diagnostic_facts.close_vs_ema20}`, source: 'newow' },
        { label: '诊断 tokens', value: jsonText(data.diagnostic_tokens), source: 'newow' },
        { label: '排除重绘输入', value: jsonText(data.diagnostic_facts.repainting_inputs_excluded), source: 'newow' },
      ],
    },
    {
      id: 'newow-window-comparison', title: '参数比较',
      summary: '10 / 20 / 24 / 30 / 52',
      updatedAt: data.diagnostic_facts.as_of,
      tone: 'warning',
      rows: [
        { label: '研究可信度', value: '不可用于可信研究（页面同 Bar 收盘口径）', source: 'newow' },
        ...data.page_window_comparison.map(item => ({
          label: `窗口 ${item.window}`,
          value: `收益 ${item.cumulative_return_pct}% · 回撤 ${item.max_drawdown_pct}% · 交易 ${item.trade_count} · 胜率 ${item.win_rate_pct}% · 分数 ${item.score}`,
          source: 'newow' as const,
        })),
      ],
    },
    {
      id: 'newow-evidence', title: '公式与证据边界',
      summary: '页面一致性 + clean-room + observation-only',
      updatedAt: data.diagnostic_facts.as_of,
      tone: 'warning',
      rows: [
        { label: '页面一致性复算', value: data.semantic_labels.page_parity ? '是' : '否', source: 'newow' },
        { label: 'Clean-room 分离', value: data.semantic_labels.cleanroom_separated ? '是' : '否', source: 'newow' },
        { label: '仅供研究观察', value: data.semantic_labels.observation_only ? '是' : '否', source: 'newow' },
        { label: '因果研究结果', value: data.semantic_labels.causal_research_result ? '是' : '否', source: 'newow' },
        { label: '使用重绘输入', value: data.semantic_labels.repainting_input_used ? '是' : '否', source: 'newow' },
        { label: '公式身份', value: jsonText(data.formula_descriptions), source: 'newow' },
      ],
    },
    {
      id: 'newow-data', title: '主力与数据', summary: latestBar?.physical_contract ?? '不可用',
      updatedAt: latestBar?.bar_end ?? null,
      tone: latestBar ? 'default' : 'unavailable',
      rows: [
        { label: '序列', value: '真实主力', source: 'newow' },
        { label: '当前合约', value: latestBar?.physical_contract ?? '不可用', source: 'newow' },
        { label: '当前 Segment', value: latestBar?.segment_id ?? '不可用', source: 'newow' },
        { label: '最近换月', value: latestRollover ? jsonText(latestRollover) : '无', source: 'newow' },
        { label: 'warnings', value: jsonText(data.warnings), source: 'newow' },
        { label: '数据覆盖', value: data.bars.length > 0 ? `${data.bars[0]!.trading_day} 至 ${data.bars.at(-1)!.trading_day}` : '不可用', source: 'newow' },
        { label: '共享行情状态', value: header.freshness === 'fresh' ? '正常' : header.freshness === 'stale' ? '旧快照' : '不可用', source: 'market' },
      ],
    },
  ]
}

function formatNumber(value: number | null): string {
  return value === null ? '不可用' : String(value)
}

function formatRange(value: { minimum: number | null; maximum: number | null } | undefined): string {
  return value === undefined || value.minimum === null || value.maximum === null
    ? '不可用' : `${value.minimum}–${value.maximum}`
}

function booleanText(value: boolean | null): string {
  return value === null ? '不可用' : value ? '是' : '否'
}

function latestTrendTransition(data: NewowTrendDetailResponse) {
  for (let index = data.trend_band.length - 1; index >= 0; index -= 1) {
    const point = data.trend_band[index]!
    if (point.transition !== null) return point
  }
  return undefined
}

function latestEscapeMarker(markers: NewowTrendDetailResponse['escape_markers']) {
  return [...markers].sort((left, right) => {
    const timeOrder = Date.parse(right.bar_end) - Date.parse(left.bar_end)
    if (timeOrder !== 0) return timeOrder
    const typeOrder = D_PRIORITY[left.marker_type] - D_PRIORITY[right.marker_type]
    return typeOrder !== 0 ? typeOrder : lexical(left.marker_id, right.marker_id)
  })[0]
}

function escapeDisclosureRows(
  unavailable: boolean,
  current: NewowTrendDetailResponse['escape_markers'],
  historical: NewowTrendDetailResponse['escape_markers'][number] | undefined,
  latestBarEnd: string | undefined,
): MarketDetailDisclosureRow[] {
  return [
    {
      label: '当前 Bar D Markers',
      value: unavailable ? '不可用' : current.length > 0 ? current.map((marker) => marker.marker_type).join(' / ') : '无',
      source: 'newow',
    },
    { label: '当前 D Bar', value: unavailable ? '不可用' : latestBarEnd ?? '不可用', source: 'newow' },
    { label: '最近历史 D Marker', value: historical?.marker_type ?? '无', source: 'newow' },
    { label: '最近历史 D Bar', value: historical?.bar_end ?? '无', source: 'newow' },
  ]
}

function cupDisclosureRows(
  unavailable: boolean,
  cup: NewowCupHandle | undefined,
): MarketDetailDisclosureRow[] {
  if (unavailable) return cupUnavailableRows()
  if (cup === undefined) return cupEmptyRows()
  return [
    { label: '杯柄 Candidate', value: cup.candidate_id, source: 'newow' },
    { label: '杯柄方向', value: cup.direction, source: 'newow' },
    { label: '杯柄当前状态', value: `${cup.state} · ${CUP_STATE_LABEL[cup.state]}`, source: 'newow' },
    { label: 'L 左杯沿', value: jsonText(cup.left_rim), source: 'newow' },
    { label: 'B 杯底', value: jsonText(cup.bottom), source: 'newow' },
    { label: 'R 右杯沿', value: jsonText(cup.right_rim), source: 'newow' },
    { label: 'H 柄起点', value: cup.handle_start_at, source: 'newow' },
    { label: 'H 柄极值', value: cup.handle_extreme ? jsonText(cup.handle_extreme) : '无', source: 'newow' },
    {
      label: 'P 枢轴',
      value: cup.pivot_price === null || cup.pivot_frozen_at === null
        ? '无' : jsonText({ pivot_frozen_at: cup.pivot_frozen_at, price: cup.pivot_price }),
      source: 'newow',
    },
    { label: 'confirmed_at', value: cup.confirmed_at, source: 'newow' },
    { label: 'first_seen_at', value: cup.first_seen_at, source: 'newow' },
    { label: 'state_changed_at', value: cup.state_changed_at, source: 'newow' },
    { label: 'score', value: String(cup.score), source: 'newow' },
    { label: 'score_breakdown', value: jsonText(cup.score_breakdown), source: 'newow' },
    { label: 'volume_facts', value: jsonText(cup.volume_facts), source: 'newow' },
  ]
}

const CUP_DISCLOSURE_LABELS = [
  '杯柄 Candidate', '杯柄方向', '杯柄当前状态', 'L 左杯沿', 'B 杯底', 'R 右杯沿',
  'H 柄起点', 'H 柄极值', 'P 枢轴', 'confirmed_at', 'first_seen_at', 'state_changed_at',
  'score', 'score_breakdown', 'volume_facts',
] as const

function cupUnavailableRows(): MarketDetailDisclosureRow[] {
  return CUP_DISCLOSURE_LABELS.map((label) => ({ label, value: '不可用', source: 'newow' }))
}

function cupEmptyRows(): MarketDetailDisclosureRow[] {
  return CUP_DISCLOSURE_LABELS.map((label) => ({ label, value: '无', source: 'newow' }))
}

function jsonText(value: object): string {
  return JSON.stringify(value)
}

function snapshotForIdentity(
  data: NewowTrendDetailResponse | null,
  identity: MarketDetailIdentity,
): NewowTrendDetailResponse | null {
  return data !== null
    && identity.view === 'trend'
    && identity.seriesKind === 'actual_dominant'
    && identity.frequency === '1d'
    && identity.symbol === data.instrument.product
    ? data : null
}

function markerTypeOrder(value: string | undefined): number {
  return value === undefined ? 0 : SAME_FAMILY_MARKER_ORDER[value] ?? 0
}

function lexical(left: string, right: string): number {
  return left < right ? -1 : left > right ? 1 : 0
}

function trendTone(value: string): MarketDetailFact['tone'] {
  if (value === '建仓' || value === '持有') return 'up'
  if (value === '清仓') return 'warning'
  return 'default'
}

function cupTone(cup: NewowCupHandle | undefined): MarketDetailFact['tone'] {
  if (cup === undefined) return 'default'
  if (cup.state === 'BREAKOUT') return cup.direction === 'BULLISH' ? 'up' : 'down'
  if (cup.state === 'WEAKENED' || cup.state === 'INVALIDATED' || cup.state === 'EXPIRED') return 'warning'
  return 'default'
}
