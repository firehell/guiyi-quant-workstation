<script setup lang="ts">
import { NSkeleton } from 'naive-ui'
</script>

<template>
  <section class="market-radar-skeleton" aria-label="Radar 加载中" data-testid="market-radar-skeleton">
    <div class="market-radar-skeleton__summary">
      <NSkeleton text width="18%" />
      <NSkeleton v-for="index in 5" :key="index" text width="72px" />
    </div>
    <div class="market-radar-skeleton__discovery">
      <div class="market-radar-skeleton__panel">
        <NSkeleton text width="32%" />
        <NSkeleton height="220px" />
      </div>
      <div class="market-radar-skeleton__panel">
        <NSkeleton text width="38%" />
        <NSkeleton v-for="index in 4" :key="index" height="58px" />
      </div>
    </div>
    <div class="market-radar-skeleton__panel market-radar-skeleton__detail">
      <NSkeleton text width="22%" />
      <NSkeleton v-for="index in 6" :key="index" text />
    </div>
  </section>
</template>

<style scoped>
.market-radar-skeleton { display: flex; flex-direction: column; gap: 16px; }
.market-radar-skeleton__summary,
.market-radar-skeleton__panel {
  display: flex;
  gap: 12px;
  padding: 16px;
  border: .5px solid var(--gy-border);
  border-radius: var(--gy-radius-lg);
  background: var(--gy-bg-panel);
  box-shadow: var(--gy-shadow-panel);
}
.market-radar-skeleton__summary { align-items: center; overflow: hidden; }
.market-radar-skeleton__summary :deep(.n-skeleton) { flex: 0 0 auto; }
.market-radar-skeleton__discovery { display: grid; grid-template-columns: minmax(0, 1.4fr) minmax(320px, .9fr); gap: 16px; }
.market-radar-skeleton__panel { flex-direction: column; }
.market-radar-skeleton__detail { min-height: 250px; }
@media (max-width: 980px) { .market-radar-skeleton__discovery { grid-template-columns: 1fr; } }
</style>
