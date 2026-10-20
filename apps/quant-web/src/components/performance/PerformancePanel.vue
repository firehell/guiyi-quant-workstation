<script setup lang="ts">
withDefaults(defineProps<{
  title?: string; kind: string; since?: string | null; through?: string | null
  cutoff?: string | null; version?: string | null; coverage?: string | null
  showDetails?: boolean; description?: string; loading?: boolean; error?: string | null
}>(), { title:'收益与参考记录', showDetails:true })
</script>
<template>
  <section class="performance-panel" :aria-label="`${kind}收益面板`" :aria-busy="loading" data-performance-version="guiyi_performance_presentation_v1">
    <slot name="header"><header class="performance-panel__header"><h2>{{ title }}</h2><span class="performance-panel__kind">{{ kind }}</span></header></slot>
    <div v-if="$slots.controls" class="performance-panel__controls"><slot name="controls" /></div>
    <p v-if="description" class="performance-panel__description">{{ description }}</p>
    <p v-if="since || through" class="performance-panel__window">统计窗口 {{ since ?? '未提供' }} → {{ through ?? '未提供' }}<span v-if="coverage"> · {{ coverage }}</span></p>
    <p v-if="loading" role="status">正在读取{{ kind }}…</p>
    <p v-else-if="error" role="alert">{{ error }}</p>
    <slot />
    <div v-if="$slots.metrics" class="performance-panel__metrics"><slot name="metrics" /></div>
    <div v-if="$slots.records" class="performance-panel__records"><slot name="records" /></div>
    <details v-if="showDetails && ($slots.details || cutoff || version)" class="performance-panel__details"><summary>统计口径与来源</summary><slot name="details" /><p v-if="cutoff">来源截止 {{ cutoff }}</p><p v-if="version" class="performance-panel__version">计算版本 {{ version }}</p></details>
  </section>
</template>
<style scoped>
.performance-panel{min-width:0;display:grid;gap:var(--gy-space-2);background:var(--gy-bg-panel);border:1px solid var(--gy-border);border-radius:var(--gy-radius-lg);padding:var(--gy-panel-padding);color:var(--gy-text-primary)}
.performance-panel__header{display:flex;gap:12px;align-items:baseline;justify-content:space-between;flex-wrap:wrap}.performance-panel__header h2{font-size:var(--gy-font-size-lg);margin:0}.performance-panel__kind{color:var(--gy-detail-accent);font-size:12px;font-weight:600}.performance-panel__description,.performance-panel__window,.performance-panel__details{font-size:12px;line-height:1.6;color:var(--gy-text-muted)}.performance-panel__controls{display:flex;gap:8px;flex-wrap:wrap;align-items:center}.performance-panel__version{overflow-wrap:anywhere}.performance-panel__details summary{cursor:pointer}.performance-panel__metrics,.performance-panel__records{min-width:0}
</style>
