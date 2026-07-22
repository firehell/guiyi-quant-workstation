<script setup lang="ts">
import type { MarketRightRailTab } from '@/utils/marketRightRail'

defineProps<{ modelValue: MarketRightRailTab }>()
const emit = defineEmits<{ 'update:modelValue': [value: MarketRightRailTab] }>()

const tabs: Array<{ name: MarketRightRailTab; label: string }> = [
  { name: 'strategy', label: '策略' },
  { name: 'signal', label: '信号' },
  { name: 'review', label: '复盘' },
  { name: 'runtime', label: '运行' },
]
</script>

<template>
  <aside class="market-right-rail" aria-label="Market 研究右栏">
    <div class="market-right-rail__tabs" role="tablist" aria-label="Market 研究视图">
      <button
        v-for="tab in tabs"
        :id="`market-rail-tab-${tab.name}`"
        :key="tab.name"
        type="button"
        role="tab"
        :aria-selected="modelValue === tab.name"
        :aria-controls="`market-rail-panel-${tab.name}`"
        :tabindex="modelValue === tab.name ? 0 : -1"
        @click="emit('update:modelValue', tab.name)"
      >
        {{ tab.label }}
      </button>
    </div>
    <section
      :id="`market-rail-panel-${modelValue}`"
      class="market-right-rail__pane"
      role="tabpanel"
      :aria-labelledby="`market-rail-tab-${modelValue}`"
    >
      <slot :name="modelValue" />
    </section>
  </aside>
</template>

<style scoped>
.market-right-rail {
  min-width: 0;
  max-height: calc(100vh - var(--gy-header-height) - (var(--gy-content-padding) * 2));
  padding: var(--gy-space-2);
  overflow-y: auto;
  background: var(--gy-bg-canvas);
  border: 1px solid var(--gy-border);
  border-radius: var(--gy-radius-lg);
}

.market-right-rail__tabs {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 2px;
  padding: 3px;
  background: var(--gy-bg-panel-strong);
  border-radius: var(--gy-radius-md);
}

.market-right-rail__tabs button {
  min-height: 28px;
  padding: 4px 6px;
  color: var(--gy-text-muted);
  background: transparent;
  border: 0;
  border-radius: var(--gy-radius-sm);
  cursor: pointer;
}

.market-right-rail__tabs button[aria-selected='true'] {
  color: var(--gy-text-primary);
  background: var(--gy-bg-selected);
  box-shadow: inset 0 0 0 1px var(--gy-border-focus);
}

.market-right-rail__tabs button:focus-visible {
  outline: 2px solid var(--gy-accent-hover);
  outline-offset: 1px;
}

.market-right-rail__pane {
  display: flex;
  flex-direction: column;
  gap: var(--gy-space-3);
  padding-top: var(--gy-space-3);
}

@media (max-width: 1199px) {
  .market-right-rail {
    max-height: none;
    overflow: visible;
  }
}
</style>
