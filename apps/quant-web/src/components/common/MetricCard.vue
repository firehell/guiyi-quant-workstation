<script setup lang="ts">
/** 指标卡片：展示 label / 主数值 / 辅助 meta，支持涨跌色调 */
withDefaults(
  defineProps<{
    label: string
    value: string | number
    meta?: string
    tone?: 'default' | 'info' | 'up' | 'down' | 'warning'
    loading?: boolean
  }>(),
  { meta: '', tone: 'default', loading: false },
)
</script>

<template>
  <article class="metric-card" :class="`metric-card--${tone}`">
    <div class="metric-card__head">
      <span class="metric-card__label">{{ label }}</span>
      <slot name="badge" />
    </div>
    <div v-if="loading" class="metric-card__skeleton" aria-label="加载中" />
    <strong v-else class="metric-card__value gy-number">{{ value }}</strong>
    <span v-if="meta" class="metric-card__meta">{{ meta }}</span>
    <slot />
  </article>
</template>

<style scoped>
.metric-card {
  min-width: 0;
  min-height: 112px;
  padding: 15px 16px;
  background: var(--gy-bg-panel);
  border: 1px solid var(--gy-border);
  border-radius: var(--gy-radius-lg);
  box-shadow: var(--gy-shadow-panel);
}

.metric-card__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--gy-space-2);
}

.metric-card__label,
.metric-card__meta {
  color: var(--gy-text-muted);
  font-size: var(--gy-font-size-sm);
}

.metric-card__value {
  display: block;
  margin-top: 11px;
  color: var(--gy-text-primary);
  font-size: var(--gy-font-size-2xl);
  line-height: 1;
}

.metric-card__meta {
  display: block;
  margin-top: 9px;
}

.metric-card--info .metric-card__value { color: var(--gy-status-info); }
.metric-card--up .metric-card__value { color: var(--gy-up); }
.metric-card--down .metric-card__value { color: var(--gy-down); }
.metric-card--warning .metric-card__value { color: var(--gy-status-warning); }

.metric-card__skeleton {
  width: 52%;
  height: 26px;
  margin-top: 13px;
  border-radius: var(--gy-radius-sm);
  background: linear-gradient(90deg, var(--gy-bg-panel-strong), var(--gy-bg-elevated), var(--gy-bg-panel-strong));
  background-size: 200% 100%;
  animation: metric-loading 1.4s linear infinite;
}

@keyframes metric-loading {
  to { background-position: -200% 0; }
}
</style>
