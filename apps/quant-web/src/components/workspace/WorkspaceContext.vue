<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { parseWorkspaceContext } from '@/utils/workspaceContext'

const route = useRoute()
const context = computed(() => parseWorkspaceContext(route.query))
const items = computed(() =>
  [
    context.value.symbol,
    context.value.contract,
    context.value.period,
    context.value.mode,
    context.value.contractView,
  ].filter((item): item is string => Boolean(item)),
)
</script>

<template>
  <div v-if="items.length" class="workspace-context" aria-label="研究上下文">
    <span v-for="item in items" :key="item">{{ item }}</span>
  </div>
</template>

<style scoped>
.workspace-context {
  display: flex;
  align-items: center;
  gap: 5px;
  min-width: 0;
  overflow: hidden;
}

.workspace-context span {
  padding: 3px 6px;
  overflow: hidden;
  color: var(--gy-text-secondary);
  font-family: var(--gy-font-mono);
  font-size: 10px;
  text-overflow: ellipsis;
  white-space: nowrap;
  background: var(--gy-bg-panel-strong);
  border: 1px solid var(--gy-border-subtle);
  border-radius: var(--gy-radius-sm);
}

@media (max-width: 1199px) {
  .workspace-context span:nth-child(n + 4) {
    display: none;
  }
}
</style>
