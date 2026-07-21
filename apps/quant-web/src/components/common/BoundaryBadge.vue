<script setup lang="ts">
/** 边界徽章：强调「研究工作站，不自动下单」 */
import UiIcon from '@/components/common/UiIcon.vue'

withDefaults(
  defineProps<{
    compact?: boolean
  }>(),
  { compact: false },
)
</script>

<template>
  <span class="boundary-badge" :class="{ 'boundary-badge--compact': compact }">
    <UiIcon name="shield" :size="14" />
    <span>{{ compact ? '不自动下单' : '研究工作站 · 不自动下单' }}</span>
  </span>
</template>

<style scoped>
.boundary-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-height: 28px;
  padding: 4px 10px;
  color: var(--gy-status-warning);
  background: var(--gy-status-warning-soft);
  border: 1px solid rgba(255, 143, 31, 0.28);
  border-radius: var(--gy-radius-pill);
  font-size: var(--gy-font-size-xs);
  white-space: nowrap;
}

.boundary-badge--compact {
  width: 100%;
  justify-content: center;
  border-radius: var(--gy-radius-md);
}
</style>
