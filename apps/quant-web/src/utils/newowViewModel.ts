import type {
  DetailViewModel,
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
      text: '建仓、持有、清仓、空仓为趋势引擎状态，不代表实际账户持仓。',
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
  const cupUnavailable = data.warnings.includes('NEWOW_CUP_WARMUP_INSUFFICIENT')
  const cup = cupUnavailable
    ? undefined : latestCup(data.cup_handles)
  return [
    {
      id: 'newow-trend', title: '趋势判断', summary: facts[0].value,
      updatedAt: latestBar?.bar_end ?? null,
      tone: facts[0].tone === 'unavailable' ? 'unavailable' : 'default',
      rows: [
        { label: '当前趋势带', value: latestBand?.state ?? '不可用', source: 'newow' },
        { label: '最近转换', value: latestBand?.transition ?? '无', source: 'newow' },
        { label: '当前物理合约', value: latestBar?.physical_contract ?? '不可用', source: 'newow' },
        { label: '分析截至 completed D1', value: latestBar?.bar_end ?? '不可用', source: 'newow' },
      ],
    },
    {
      id: 'newow-risk-shape', title: '风险与形态', summary: `${facts[1].value} · ${facts[2].value}`,
      updatedAt: latestBar?.bar_end ?? null,
      tone: facts[1].tone === 'unavailable' || facts[2].tone === 'unavailable' ? 'unavailable' : 'default',
      rows: [
        { label: '最近 D1 / D2 / D3', value: facts[1].value, source: 'newow' },
        { label: '杯柄方向', value: cupUnavailable ? '不可用' : cup?.direction ?? '无', source: 'newow' },
        { label: '杯柄生命周期', value: cupUnavailable ? '不可用' : cup ? CUP_STATE_LABEL[cup.state] : '无', source: 'newow' },
        { label: '杯柄状态时间', value: cupUnavailable ? '不可用' : cup?.state_changed_at ?? '无', source: 'newow' },
      ],
    },
    {
      id: 'newow-data', title: '主力与数据', summary: latestBar?.physical_contract ?? '不可用',
      updatedAt: latestBar?.bar_end ?? null,
      tone: latestBar ? 'default' : 'unavailable',
      rows: [
        { label: '序列', value: '真实主力', source: 'newow' },
        { label: '当前合约', value: latestBar?.physical_contract ?? '不可用', source: 'newow' },
        { label: '可见换月', value: data.rollover_seams.length > 0 ? '是' : '否', source: 'newow' },
        { label: '数据覆盖', value: data.bars.length > 0 ? `${data.bars[0]!.trading_day} 至 ${data.bars.at(-1)!.trading_day}` : '不可用', source: 'newow' },
        { label: '共享行情状态', value: header.freshness === 'fresh' ? '正常' : header.freshness === 'stale' ? '旧快照' : '不可用', source: 'market' },
      ],
    },
  ]
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
  if (value === 'NEWOW_ESCAPE_D1') return 0
  if (value === 'NEWOW_ESCAPE_D2') return 1
  if (value === 'NEWOW_ESCAPE_D3') return 2
  return 0
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
