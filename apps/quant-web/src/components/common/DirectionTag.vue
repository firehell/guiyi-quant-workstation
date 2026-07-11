<script setup lang="ts">
import { computed } from 'vue'
import UiIcon from '@/components/common/UiIcon.vue'

const props = defineProps<{
  direction?: string | null
  label?: string
}>()

const normalized = computed(() => String(props.direction || '').toLowerCase())
const tone = computed(() => {
  if (['long', 'buy', 'up', '多', '涨'].includes(normalized.value)) return 'up'
  if (['short', 'sell', 'down', '空', '跌'].includes(normalized.value)) return 'down'
  return 'neutral'
})
const text = computed(() => {
  if (props.label) return props.label
  if (tone.value === 'up') return '多'
  if (tone.value === 'down') return '空'
  return props.direction || '中性'
})
</script>

<template>
  <span class="direction-tag" :class="`direction-tag--${tone}`">
    <UiIcon v-if="tone !== 'neutral'" :name="tone === 'up' ? 'arrow-up' : 'arrow-down'" :size="12" />
    {{ text }}
  </span>
</template>

<style scoped>
.direction-tag {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  min-height: 23px;
  padding: 2px 7px;
  border: 1px solid transparent;
  border-radius: var(--gy-radius-sm);
  color: var(--gy-neutral);
  background: rgba(130, 144, 166, 0.1);
  font-size: var(--gy-font-size-xs);
  font-weight: 600;
  white-space: nowrap;
}

.direction-tag--up {
  color: var(--gy-up);
  background: var(--gy-up-soft);
  border-color: rgba(250, 81, 81, 0.2);
}

.direction-tag--down {
  color: var(--gy-down);
  background: var(--gy-down-soft);
  border-color: rgba(7, 193, 96, 0.2);
}
</style>
