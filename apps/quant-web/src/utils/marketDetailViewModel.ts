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
    extendedSections: marketDisclosure(input, latest!.time, freshness),
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
    extendedSections: marketDisclosure(input, null, 'unavailable'),
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
  updatedAt: string | null,
  freshness: MarketDetailHeaderModel['freshness'],
): readonly MarketDetailDisclosureSection[] {
  const rows = [
    { label: '数据来源', value: displaySource(input.overlaySource), source: 'market' as const },
    { label: '数据覆盖', value: input.canonicalCoverage ? `${input.canonicalCoverage.start} 至 ${input.canonicalCoverage.end}` : '不可用', source: 'market' as const },
    { label: '更早历史', value: input.hasMoreBefore ? '可继续加载' : '已到当前加载边界', source: 'market' as const },
  ]
  return [{
    id: 'market-data',
    title: '行情数据',
    summary: freshness === 'unavailable' ? '行情数据不可用' : freshness === 'stale' ? '正在展示上一份成功快照' : '当前行情事实',
    updatedAt,
    tone: freshness === 'fresh' ? 'default' : freshness === 'stale' ? 'warning' : 'unavailable',
    rows,
  }]
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
