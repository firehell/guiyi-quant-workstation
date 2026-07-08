<script setup lang="ts">
import { NAlert } from 'naive-ui'
import EmptyState from '@/components/common/EmptyState.vue'

defineProps<{
  title?: string
  subtitle?: string
  error?: string | null
  loading?: boolean
}>()
</script>

<template>
  <div class="page-shell">
    <header v-if="title || $slots.actions" class="page-shell__header">
      <div>
        <h2 v-if="title" class="page-shell__title">{{ title }}</h2>
        <p v-if="subtitle" class="page-shell__subtitle">{{ subtitle }}</p>
      </div>
      <div v-if="$slots.actions" class="page-shell__actions">
        <slot name="actions" />
      </div>
    </header>
    <NAlert v-if="error" type="error" :bordered="false">{{ error }}</NAlert>
    <div v-if="loading" class="page-shell__loading">加载中…</div>
    <slot v-else />
    <EmptyState v-if="$slots.empty && !loading" />
  </div>
</template>

<style scoped>
.page-shell__header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
  margin-bottom: 16px;
}

.page-shell__title {
  font-size: 20px;
  font-weight: 700;
  margin-bottom: 4px;
}

.page-shell__subtitle {
  color: var(--gy-text-muted, #94a3b8);
  font-size: 13px;
}

.page-shell__actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.page-shell__loading {
  padding: 24px 0;
  color: var(--gy-text-muted, #94a3b8);
}
</style>
