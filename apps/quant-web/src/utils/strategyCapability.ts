import type { CapabilityKind } from '@/components/common/CapabilityBadge.vue'
import type { StrategyRegistryItem } from '@/types/dashboard'

/** Registry 能力分类（与 WEB-V1-05 Gate 对齐） */
export type StrategyCapabilityCategory =
  | 'formal_historical_backtest'
  | 'research_only'
  | 'historical_scan'
  | 'live_observation'
  | 'rejected'
  | 'unavailable'

export const STRATEGY_CAPABILITY_SECTIONS: Array<{
  key: StrategyCapabilityCategory
  title: string
  hint: string
}> = [
  {
    key: 'formal_historical_backtest',
    title: '正式历史回测',
    hint: '走 Profile / quality / lineage 契约的历史回测入口；Registry ≠ validated',
  },
  {
    key: 'research_only',
    title: '仅研究',
    hint: '无可靠 machine capability 或通用模板；不可理解为已验证或可 live',
  },
  {
    key: 'historical_scan',
    title: '历史研究扫描',
    hint: '历史 bar 扫描提醒；非 live-confirmed，不自动下单',
  },
  {
    key: 'live_observation',
    title: 'Live 观察',
    hint: 'Live bar / 观察层；仍非自动交易',
  },
  {
    key: 'rejected',
    title: '已拒绝候选',
    hint: '验证结论 rejected；禁止当作 validated 或提供 live 入口',
  },
  {
    key: 'unavailable',
    title: '不可用',
    hint: '能力不可用或 legacy；禁止冒充正式能力',
  },
]

const CATEGORY_BADGE: Record<
  StrategyCapabilityCategory,
  { kind: CapabilityKind; label: string }
> = {
  formal_historical_backtest: { kind: 'formal-research', label: '历史回测' },
  research_only: { kind: 'research-only', label: '仅研究' },
  historical_scan: { kind: 'research-only', label: '历史研究扫描' },
  live_observation: { kind: 'observation-only', label: 'Live 观察' },
  rejected: { kind: 'rejected', label: '已拒绝' },
  unavailable: { kind: 'unavailable', label: '不可用' },
}

function machineCapabilityClasses(item: StrategyRegistryItem): StrategyCapabilityCategory[] {
  const fromApi = item.capability_classes?.filter(Boolean) as StrategyCapabilityCategory[] | undefined
  if (fromApi?.length) return [...new Set(fromApi)]
  return []
}

/** 解析 registry 条目的能力分类；无 machine source 时默认 research_only。 */
export function resolveStrategyCapabilityCategories(item: StrategyRegistryItem): StrategyCapabilityCategory[] {
  if (item.validation_outcome === 'rejected') return ['rejected']

  const machine = machineCapabilityClasses(item)
  if (machine.length) return machine

  const derived: StrategyCapabilityCategory[] = []
  if (item.backtest_endpoints?.length) derived.push('formal_historical_backtest')
  if (item.scan_endpoint) derived.push('historical_scan')
  if (item.live_observation) derived.push('live_observation')
  if (!derived.length) {
    if (item.capability_class === 'unavailable') return ['unavailable']
    return ['research_only']
  }
  return derived
}

export function capabilityBadgeForCategory(category: StrategyCapabilityCategory) {
  return CATEGORY_BADGE[category]
}

/** 按能力分区展示 registry；同一策略可出现在多个分区。 */
export function groupRegistryByCapability(items: StrategyRegistryItem[]) {
  const grouped = Object.fromEntries(
    STRATEGY_CAPABILITY_SECTIONS.map((section) => [section.key, [] as StrategyRegistryItem[]]),
  ) as Record<StrategyCapabilityCategory, StrategyRegistryItem[]>

  for (const item of items) {
    for (const category of resolveStrategyCapabilityCategories(item)) {
      grouped[category].push(item)
    }
  }
  return grouped
}

export function isRejectedStrategy(item: StrategyRegistryItem) {
  return item.validation_outcome === 'rejected' || resolveStrategyCapabilityCategories(item).includes('rejected')
}

export function allowsLiveObservationAction(item: StrategyRegistryItem) {
  return !isRejectedStrategy(item) && resolveStrategyCapabilityCategories(item).includes('live_observation')
}
