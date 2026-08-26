import type { SubingLifecycleSnapshot } from '@/types/market'

export interface SubingLifecyclePivotFact {
  role: 'trigger' | 'bound'
  label: string
  price: number
}

export function buildSubingLifecyclePivotFacts(
  lifecycle: Pick<
    SubingLifecycleSnapshot,
    'trigger_reference_pivot' | 'bound_reference_pivot'
  >,
): SubingLifecyclePivotFact[] {
  const facts: SubingLifecyclePivotFact[] = []
  const trigger = lifecycle.trigger_reference_pivot
  if (trigger) {
    facts.push({
      role: 'trigger',
      label: trigger.kind === 'low' ? '触发前低' : '触发前高',
      price: trigger.price,
    })
  }
  const bound = lifecycle.bound_reference_pivot
  if (bound) {
    facts.push({
      role: 'bound',
      label: bound.kind === 'low' ? '绑定前低' : '绑定前高',
      price: bound.price,
    })
  }
  return facts
}
