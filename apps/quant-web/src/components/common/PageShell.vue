<script setup lang="ts">
/** 页面外壳：标题区、状态区、错误条（含重试）、加载态与内容槽位 */
import { NAlert, NButton } from 'naive-ui'
import EmptyState from '@/components/common/EmptyState.vue'

withDefaults(
  defineProps<{
    title?: string
    subtitle?: string
    error?: string | null
    loading?: boolean
    empty?: boolean
    emptyDescription?: string
    emptyKind?: 'no-data' | 'filtered' | 'error'
    density?: 'comfortable' | 'compact'
    retryLabel?: string
  }>(),
  {
    density: 'comfortable',
    empty: false,
    emptyKind: 'no-data',
    retryLabel: '重试',
  },
)

const emit = defineEmits<{
  retry: []
}>()
</script>

<template>
  <div class="page-shell" :class="`page-shell--${density}`">
    <header v-if="title || $slots.actions || $slots.badges" class="page-shell__header">
      <div class="page-shell__heading">
        <div v-if="$slots.badges" class="page-shell__badges">
          <slot name="badges" />
        </div>
        <h2 v-if="title" class="page-shell__title">{{ title }}</h2>
        <p v-if="subtitle" class="page-shell__subtitle">{{ subtitle }}</p>
      </div>
      <div v-if="$slots.actions" class="page-shell__actions">
        <slot name="actions" />
      </div>
    </header>

    <div v-if="$slots.status" class="page-shell__status">
      <slot name="status" />
    </div>

    <NAlert v-if="error" type="error" :bordered="false" class="page-shell__error">
      <div class="page-shell__error-row">
        <span>{{ error }}</span>
        <NButton size="tiny" secondary :aria-label="retryLabel" @click="emit('retry')">
          {{ retryLabel }}
        </NButton>
      </div>
    </NAlert>

    <div v-if="loading" class="page-shell__loading" role="status" aria-live="polite">加载中…</div>
    <template v-else>
      <EmptyState
        v-if="empty"
        :kind="emptyKind"
        :description="emptyDescription"
      >
        <template v-if="$slots.emptyExtra" #extra>
          <slot name="emptyExtra" />
        </template>
      </EmptyState>
      <slot v-else />
    </template>
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

.page-shell__heading {
  min-width: 0;
}

.page-shell__badges {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 6px;
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

.page-shell__error {
  margin-bottom: var(--gy-space-4);
}

.page-shell__error-row {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.page-shell__loading {
  padding: var(--gy-space-6) 0;
  color: var(--gy-text-muted);
}

.page-shell--compact .page-shell__header {
  margin-bottom: var(--gy-space-3);
}

@media (max-width: 1439px) {
  .page-shell__header {
    gap: 12px;
  }
}

@media (max-width: 1279px) {
  .page-shell__header {
    align-items: stretch;
    flex-direction: column;
  }

  .page-shell__actions {
    width: 100%;
  }
}

@media (max-width: 1023px) {
  .page-shell__title {
    font-size: var(--gy-font-size-lg);
  }
}
</style>
