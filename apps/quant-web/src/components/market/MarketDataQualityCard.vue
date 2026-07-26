<script setup lang="ts">
import { ref } from 'vue'
import { NButton, NTag } from 'naive-ui'
import type {
  MarketQualityAction,
  MarketQualityImpact,
} from '@/utils/marketQualityPresentation'

defineProps<{
  impact: MarketQualityImpact
}>()

const emit = defineEmits<{
  action: [value: MarketQualityAction]
}>()

const root = ref<HTMLElement | null>(null)

const actionLabels: Record<MarketQualityAction, string> = {
  evidence: '查看冲突证据',
  profile: '选择 Profile',
  actual: '切换真实主力',
}

function focus() {
  root.value?.focus({ preventScroll: true })
  root.value?.scrollIntoView({ behavior: 'smooth', block: 'center' })
}

defineExpose({ focus })
</script>

<template>
  <section
    ref="root"
    class="market-data-quality-card"
    :class="`market-data-quality-card--${impact.severity}`"
    role="region"
    aria-label="数据质量影响"
    tabindex="-1"
  >
    <header>
      <div>
        <span class="market-data-quality-card__eyebrow">数据质量影响</span>
        <h2>{{ impact.title }}</h2>
      </div>
      <NTag size="small" :type="impact.severity">{{ impact.severity === 'error' ? 'Failed' : 'Warning' }}</NTag>
    </header>

    <div class="market-data-quality-card__body">
      <div>
        <h3>发生原因</h3>
        <ul>
          <li v-for="reason in impact.reasons" :key="reason">{{ reason }}</li>
        </ul>
      </div>
      <div>
        <h3>仍可进行</h3>
        <ul>
          <li v-for="item in impact.allowed" :key="item">{{ item }}</li>
        </ul>
      </div>
      <div>
        <h3>当前阻断</h3>
        <ul>
          <li v-for="item in impact.blocked" :key="item">{{ item }}</li>
        </ul>
      </div>
    </div>

    <footer>
      <NButton
        v-for="action in impact.actions"
        :key="action"
        size="small"
        secondary
        @click="emit('action', action)"
      >
        {{ actionLabels[action] }}
      </NButton>
    </footer>
  </section>
</template>

<style scoped>
.market-data-quality-card {
  --quality-accent: var(--gy-status-warning);
  display: grid;
  gap: var(--gy-space-3);
  padding: var(--gy-space-3) var(--gy-space-4);
  background: var(--gy-surface-warning);
  border: 1px solid color-mix(in srgb, var(--quality-accent) 42%, transparent);
  border-left: 3px solid var(--quality-accent);
  border-radius: var(--gy-radius-md);
  outline: none;
}

.market-data-quality-card--error {
  --quality-accent: var(--gy-status-error);
  background: var(--gy-surface-error);
}

.market-data-quality-card:focus-visible {
  box-shadow: var(--gy-shadow-focus);
}

.market-data-quality-card header,
.market-data-quality-card footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--gy-space-3);
}

.market-data-quality-card__eyebrow {
  color: var(--quality-accent);
  font-size: var(--gy-font-size-xs);
}

.market-data-quality-card h2,
.market-data-quality-card h3,
.market-data-quality-card ul {
  margin: 0;
}

.market-data-quality-card h2 {
  margin-top: 2px;
  color: var(--gy-text-primary);
  font-size: var(--gy-font-size-md);
}

.market-data-quality-card h3 {
  color: var(--gy-text-muted);
  font-size: var(--gy-font-size-xs);
  font-weight: 500;
}

.market-data-quality-card__body {
  display: grid;
  grid-template-columns: minmax(0, 1.5fr) minmax(0, 1fr) minmax(0, 1fr);
  gap: var(--gy-space-4);
}

.market-data-quality-card ul {
  padding: 4px 0 0 18px;
  color: var(--gy-text-secondary);
  font-size: var(--gy-font-size-sm);
  line-height: 1.55;
}

.market-data-quality-card footer {
  justify-content: flex-start;
}

@media (max-width: 1023px) {
  .market-data-quality-card__body {
    grid-template-columns: 1fr;
    gap: var(--gy-space-2);
  }
}
</style>
