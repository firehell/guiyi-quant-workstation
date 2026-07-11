<script setup lang="ts">
import { computed } from 'vue'
import { NEmpty } from 'naive-ui'

const props = withDefaults(
  defineProps<{
    description?: string
    kind?: 'no-data' | 'filtered' | 'error'
  }>(),
  { description: '', kind: 'no-data' },
)

const fallback = computed(() => {
  if (props.kind === 'filtered') return '当前条件下暂无结果'
  if (props.kind === 'error') return '数据加载失败，请查看错误提示'
  return '暂无数据'
})
</script>

<template>
  <NEmpty :description="description || fallback" class="empty-state" :class="`empty-state--${kind}`">
    <template v-if="$slots.extra" #extra><slot name="extra" /></template>
  </NEmpty>
</template>

<style scoped>
.empty-state {
  padding: 44px 0;
  color: var(--gy-text-muted);
}

.empty-state--error {
  color: var(--gy-status-error);
}
</style>
