<script setup lang="ts">
/**
 * 可信边界徽章：区分 formal / research / observation / live / rejected 等能力表达。
 */
import { computed } from 'vue'
import { NTag } from 'naive-ui'

export type CapabilityKind =
  | 'formal-research'
  | 'research-only'
  | 'observation-only'
  | 'historical-replay'
  | 'live-confirmed'
  | 'rejected'
  | 'unavailable'

const props = withDefaults(
  defineProps<{
    kind: CapabilityKind
    label?: string
    size?: 'small' | 'medium'
  }>(),
  { size: 'small' },
)

const META: Record<
  CapabilityKind,
  { label: string; type: 'default' | 'info' | 'success' | 'warning' | 'error'; title: string }
> = {
  'formal-research': {
    label: '正式研究',
    type: 'info',
    title: '正式研究能力：走 Profile / quality / lineage 契约，非实盘',
  },
  'research-only': {
    label: '仅研究',
    type: 'warning',
    title: '研究-only：不可理解为已验证或可 live',
  },
  'observation-only': {
    label: '仅观察',
    type: 'default',
    title: '前端或观察层计算，不是 StrategySignal',
  },
  'historical-replay': {
    label: '历史回放',
    type: 'warning',
    title: '测试/回放数据，不是 live-confirmed',
  },
  'live-confirmed': {
    label: 'Live 已确认',
    type: 'success',
    title: '已确认 Live bar / 事件，仍非自动下单',
  },
  rejected: {
    label: '已拒绝候选',
    type: 'error',
    title: '验证结论为 rejected，不可当作 validated',
  },
  unavailable: {
    label: '不可用',
    type: 'default',
    title: '能力不可用或 legacy，禁止冒充正式能力',
  },
}

const meta = computed(() => META[props.kind])
const display = computed(() => props.label || meta.value.label)
</script>

<template>
  <NTag
    class="capability-badge"
    :type="meta.type"
    :size="size"
    :title="meta.title"
    :bordered="false"
  >
    {{ display }}
  </NTag>
</template>

<style scoped>
.capability-badge {
  font-weight: 600;
  letter-spacing: 0.02em;
}
</style>
