import type {
  BarData,
  DominantContractItem,
  MarketOverlaySource,
  MarketReadState,
  ProductResearchResponse,
} from '../types/market.ts'
import type {
  MarketDetailDisclosureSection,
  MarketDetailHeaderModel,
  MarketDetailIdentity,
} from '../types/marketDetail.ts'

export interface MarketDetailHeaderInput {
  identity: MarketDetailIdentity
  dominant: DominantContractItem | null
  bars: readonly BarData[]
  research: ProductResearchResponse | null
  marketState: MarketReadState | null
  overlaySource: MarketOverlaySource
  canonicalCoverage: { start: string; end: string } | null
  hasMoreBefore: boolean
  stale: boolean
}

/**
 * Builds only sourced market facts for the shared detail header. Strategy
 * formulas and view conclusions remain owned by their later view workspaces.
 */
export function buildMarketDetailHeaderModel(input: MarketDetailHeaderInput): MarketDetailHeaderModel {
  const identity = input.identity
  const dominant = matchingDominant(input.dominant, identity.symbol)
  const research = matchingResearch(input.research, identity)
  const state = matchingState(input.marketState, identity)
  const bars = sortedBars(input.bars)
  const latest = bars.at(-1) ?? null
  const previous = bars.at(-2) ?? null
  const mismatch = hasIdentityMismatch(input, latest, dominant)
  const unavailable = !latest || mismatch
  const freshness: MarketDetailHeaderModel['freshness'] = unavailable
    ? 'unavailable'
    : input.stale ? 'stale' : 'fresh'
  const product = dominant ?? research

  if (unavailable) return unavailableHeader(input, product, state)

  const displayContract = resolveDisplayContract(identity, latest!)
  const change = previous ? latest!.close - previous.close : null
  const pct = previous && previous.close !== 0 ? change! / previous.close * 100 : null
  return {
    symbol: identity.symbol,
    productName: product?.product_name ?? identity.symbol.toUpperCase(),
    exchange: product?.exchange ?? '',
    sector: product?.sector ?? '',
    seriesKind: identity.seriesKind,
    displayContract,
    asOf: latest!.time,
    open: latest!.open,
    high: latest!.high,
    low: latest!.low,
    close: latest!.close,
    change,
    pct,
    volume: latest!.volume,
    turnover: latest!.turnover ?? null,
    openInterest: latest!.openInterest ?? null,
    phase: state?.phase ?? 'UNKNOWN',
    displaySource: displaySource(input.overlaySource),
    freshness,
    extendedSections: marketDisclosure(input, latest!, freshness, displayContract, product, state),
  }
}

function unavailableHeader(
  input: MarketDetailHeaderInput,
  product: DominantContractItem | ProductResearchResponse | null,
  state: MarketReadState | null,
): MarketDetailHeaderModel {
  return {
    symbol: input.identity.symbol,
    productName: product?.product_name ?? input.identity.symbol.toUpperCase(),
    exchange: product?.exchange ?? '',
    sector: product?.sector ?? '',
    seriesKind: input.identity.seriesKind,
    displayContract: input.identity.seriesKind === 'contract' ? input.identity.contract ?? null : null,
    asOf: null,
    open: null,
    high: null,
    low: null,
    close: null,
    change: null,
    pct: null,
    volume: null,
    turnover: null,
    openInterest: null,
    phase: state?.phase ?? 'UNKNOWN',
    displaySource: displaySource(input.overlaySource),
    freshness: 'unavailable',
    extendedSections: marketDisclosure(input, null, 'unavailable', null, product, state),
  }
}

function matchingDominant(
  dominant: DominantContractItem | null,
  symbol: string,
): DominantContractItem | null {
  return dominant && sameSymbol(dominant.product, symbol) ? dominant : null
}

function matchingResearch(
  research: ProductResearchResponse | null,
  identity: MarketDetailIdentity,
): ProductResearchResponse | null {
  if (!research || !sameSymbol(research.symbol, identity.symbol)) return null
  if (research.series_kind !== identity.seriesKind) return null
  if (identity.seriesKind === 'contract' && !sameContract(research.contract, identity.contract)) return null
  if (identity.seriesKind !== 'contract' && research.contract !== null) return null
  return research
}

function matchingState(
  state: MarketReadState | null,
  identity: MarketDetailIdentity,
): MarketReadState | null {
  if (!state) return null
  return sameSymbol(state.symbol, identity.symbol)
    && state.series_kind === identity.seriesKind
    && state.frequency === identity.frequency
    ? state
    : null
}

function hasIdentityMismatch(
  input: MarketDetailHeaderInput,
  latest: BarData | null,
  dominant: DominantContractItem | null,
): boolean {
  if (input.dominant && !dominant) return true
  if (!latest) return false
  if (input.identity.seriesKind === 'continuous') return Boolean(latest.physicalContract)
  if (input.identity.seriesKind === 'contract') {
    return !input.identity.contract
      || !!latest.physicalContract && !sameContract(latest.physicalContract, input.identity.contract)
  }
  const physicalContract = normalizeContract(latest.physicalContract)
  return !physicalContract
    || !!dominant && !sameContract(physicalContract, dominant.actual_contract)
}

function resolveDisplayContract(
  identity: MarketDetailIdentity,
  latest: BarData,
): string | null {
  if (identity.seriesKind === 'continuous') return null
  if (identity.seriesKind === 'contract') return identity.contract ?? null
  return normalizeContract(latest.physicalContract) ?? null
}

function marketDisclosure(
  input: MarketDetailHeaderInput,
  latest: BarData | null,
  freshness: MarketDetailHeaderModel['freshness'],
  displayContract: string | null,
  product: DominantContractItem | ProductResearchResponse | null,
  state: MarketReadState | null,
): readonly MarketDetailDisclosureSection[] {
  const research = matchingResearch(input.research, input.identity)
  const tone = freshness === 'fresh' ? 'default' : freshness === 'stale' ? 'warning' : 'unavailable'
  const unavailableSummary = freshness === 'unavailable' ? '关键行情身份不可证明' : freshness === 'stale' ? '正在展示上一份成功快照' : '当前行情事实'
  return [
    {
      id: 'market-extension',
      title: '行情扩展',
      summary: unavailableSummary,
      updatedAt: latest?.time ?? null,
      tone,
      rows: [
        { label: '成交额', value: numberText(latest?.turnover), source: 'market' },
        { label: '5日涨跌', value: '—', source: 'market' },
        { label: '量比20', value: numberText(research?.volume_ratio20), source: 'market' },
        { label: 'OI 1D', value: percentText(research?.oi_change_1d), source: 'market' },
        { label: '20日位置', value: percentText(research?.position20), source: 'market' },
        { label: '距20日高', value: percentText(research?.distance_to_20d_high), source: 'market' },
        { label: '距20日低', value: percentText(research?.distance_to_20d_low), source: 'market' },
        { label: 'ATR分位', value: percentText(research?.atr14_percentile252), source: 'market' },
      ],
    },
    {
      id: 'dominant-identity',
      title: '主力身份',
      summary: displayContract ?? '当前合约不可证明',
      updatedAt: latest?.time ?? null,
      tone,
      rows: [
        { label: '序列', value: seriesKindText(input.identity.seriesKind), source: 'market' },
        { label: '当前主力', value: currentDominant(product, research, input.identity.contract), source: 'market' },
        { label: '映射日', value: mappingDay(product, research), source: 'market' },
        { label: '物理合约区间', value: displayContract ?? '不可证明', source: 'market' },
        { label: '交易日', value: state?.trading_day ?? '—', source: 'market' },
        { label: '交易所', value: product?.exchange || '—', source: 'market' },
        { label: '板块', value: product?.sector || '—', source: 'market' },
      ],
    },
    {
      id: 'data-trust',
      title: '数据可信',
      summary: unavailableSummary,
      updatedAt: latest?.time ?? null,
      tone,
      rows: [
        { label: '数据覆盖', value: input.canonicalCoverage ? `${input.canonicalCoverage.start} 至 ${input.canonicalCoverage.end}` : '不可用', source: 'market' },
        { label: '更早历史', value: input.hasMoreBefore ? '可继续加载' : '已到当前加载边界', source: 'market' },
        { label: '展示来源', value: displaySource(input.overlaySource), source: 'market' },
        { label: '市场阶段', value: phaseText(state?.phase), source: 'market' },
        { label: '可接入Live', value: yesNo(state?.live_eligible), source: 'market' },
        { label: 'Live可用', value: yesNo(state?.live_available), source: 'market' },
        { label: '当前状态', value: freshness === 'fresh' ? '数据正常' : freshness === 'stale' ? '旧快照' : '不可用', source: 'market' },
      ],
    },
  ]
}

function sortedBars(bars: readonly BarData[]): BarData[] {
  return [...bars].sort((left, right) => Date.parse(left.time) - Date.parse(right.time))
}

function sameSymbol(left: string | null | undefined, right: string | null | undefined): boolean {
  return left?.trim().toLowerCase() === right?.trim().toLowerCase()
}

function sameContract(left: string | null | undefined, right: string | null | undefined): boolean {
  return normalizeContract(left) !== undefined && normalizeContract(left) === normalizeContract(right)
}

function normalizeContract(value: string | null | undefined): string | undefined {
  const normalized = value?.trim().toUpperCase()
  return normalized || undefined
}

function displaySource(source: MarketOverlaySource): string {
  if (source === 'realtime') return '实时观察'
  if (source === 'post_close') return '盘后观察'
  return 'Canonical'
}

function numberText(value: number | null | undefined): string {
  return value === null || value === undefined ? '—' : value.toLocaleString('zh-CN', { maximumFractionDigits: 2 })
}

function percentText(value: number | null | undefined): string {
  return value === null || value === undefined ? '—' : `${(value * 100).toFixed(2)}%`
}

function seriesKindText(seriesKind: MarketDetailIdentity['seriesKind']): string {
  if (seriesKind === 'continuous') return '主连'
  if (seriesKind === 'contract') return '指定合约'
  return '真实主力'
}

function currentDominant(
  product: DominantContractItem | ProductResearchResponse | null,
  research: ProductResearchResponse | null,
  contract: string | undefined,
): string {
  if (product && 'actual_contract' in product) return product.actual_contract
  return contract ?? research?.current_dominant ?? '—'
}

function mappingDay(
  product: DominantContractItem | ProductResearchResponse | null,
  research: ProductResearchResponse | null,
): string {
  if (product && 'dominant_mapping_date' in product) return product.dominant_mapping_date
  return research?.dominant_mapping_date ?? '—'
}

function phaseText(phase: MarketReadState['phase'] | undefined): string {
  if (phase === 'TRADING') return '交易中'
  if (phase === 'BREAK') return '盘中休市'
  if (phase === 'CLOSED') return '已收盘'
  return '状态未知'
}

function yesNo(value: boolean | undefined): string {
  return value ? '是' : '否'
}
