<script setup lang="ts">
import { NAlert } from 'naive-ui'
import EmptyState from '@/components/common/EmptyState.vue'

defineProps<{
  title?: string
  subtitle?: string
  error?: string | null
  loading?: boolean
  density?: 'comfortable' | 'compact'
}>()
</script>

<template>
  <div class="page-shell" :class="`page-shell--${density || 'comfortable'}`">
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
    <div v-if="$slots.status" class="page-shell__status"><slot name="status" /></div>
    <div v-if="loading" class="page-shell__loading">加载中…</div>
    <slot v-else />
    <EmptyState v-if="$slots.empty && !loading" />
  </div>
</template>

<style scoped>
.page-shell {
  min-width: 0;
}

.page-shell__header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
  margin-bottom: var(--gy-space-4);
}

.page-shell__title {
  font-size: var(--gy-font-size-xl);
  font-weight: 700;
  margin-bottom: var(--gy-space-1);
  letter-spacing: 0.01em;
}

.page-shell__subtitle {
  color: var(--gy-text-muted);
  font-size: var(--gy-font-size-base);
}

.page-shell__actions {
  display: flex;
  gap: var(--gy-space-2);
  flex-wrap: wrap;
}

.page-shell__status {
  margin-bottom: var(--gy-space-4);
}

.page-shell__loading {
  padding: var(--gy-space-6) 0;
  color: var(--gy-text-muted);
}

.page-shell--compact .page-shell__header {
  margin-bottom: var(--gy-space-3);
}

@media (max-width: 1199px) {
  .page-shell__header {
    align-items: stretch;
  }
}
</style>
