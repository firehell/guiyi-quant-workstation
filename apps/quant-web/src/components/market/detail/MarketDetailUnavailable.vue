<script setup lang="ts">
import MarketDetailIcon from './MarketDetailIcon.vue'

withDefaults(defineProps<{
  title?: string
  message: string
  recoveryLabel?: string
  canRecover?: boolean
  canReturnLegacy?: boolean
}>(), {
  title: '当前视角不可用',
  recoveryLabel: '恢复安全设置',
  canRecover: false,
  canReturnLegacy: true,
})

const emit = defineEmits<{
  recover: []
  'return-legacy': []
}>()
</script>

<template>
  <section class="detail-unavailable" role="status" data-detail-section="unavailable">
    <MarketDetailIcon name="warning" :size="24" />
    <div>
      <h2>{{ title }}</h2>
      <p>{{ message }}</p>
      <div class="detail-unavailable__actions">
        <button v-if="canRecover" type="button" @click="emit('recover')">{{ recoveryLabel }}</button>
        <button v-if="canReturnLegacy" type="button" @click="emit('return-legacy')">返回旧版详情</button>
      </div>
    </div>
  </section>
</template>

<style scoped>
.detail-unavailable { display: grid; grid-template-columns: auto minmax(0, 1fr); gap: var(--gy-space-3); padding: var(--gy-space-5); border: 1px solid var(--gy-detail-warning-border); border-radius: var(--gy-radius-lg); color: var(--gy-text-primary); background: var(--gy-surface-warning); }
.detail-unavailable h2 { margin: 0; font-size: var(--gy-font-size-lg); }
.detail-unavailable p { margin: var(--gy-space-2) 0 var(--gy-space-3); color: var(--gy-text-secondary); line-height: 1.6; }
.detail-unavailable__actions { display: flex; flex-wrap: wrap; gap: var(--gy-space-2); }
.detail-unavailable button { min-height: 44px; padding: 0 var(--gy-space-3); border: 1px solid var(--gy-border-strong); border-radius: var(--gy-radius-md); color: var(--gy-text-primary); background: var(--gy-bg-panel); font: inherit; cursor: pointer; }
.detail-unavailable button:hover { background: var(--gy-bg-hover); }
.detail-unavailable button:focus-visible { outline: 2px solid var(--gy-border-focus); outline-offset: 2px; }
</style>
