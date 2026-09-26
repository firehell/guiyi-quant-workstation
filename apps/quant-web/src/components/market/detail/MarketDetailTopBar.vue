<script setup lang="ts">
import MarketDetailIcon from './MarketDetailIcon.vue'

defineProps<{
  productName: string
  symbol: string
  displayContract: string | null
  historyLabel?: string
  hideBack?: boolean
  actions: {
    canOpenHistory: boolean
    canManageAlert: boolean
  }
}>()

const emit = defineEmits<{
  back: []
  'select-symbol': []
  'open-history': []
  'open-alert': []
}>()
</script>

<template>
  <header class="detail-topbar" :class="{ 'detail-topbar--without-back': hideBack }" data-detail-section="topbar">
    <button v-if="!hideBack" class="detail-topbar__back" type="button" aria-label="返回市场" @click="emit('back')">
      <MarketDetailIcon name="back" />
      <span>返回市场</span>
    </button>

    <button class="detail-topbar__identity" type="button" aria-label="切换品种或合约" @click="emit('select-symbol')">
      <span class="detail-topbar__name">{{ productName }}</span>
      <span class="detail-topbar__contract">{{ displayContract || symbol.toUpperCase() }}</span>
      <MarketDetailIcon name="chevron-down" :size="18" />
    </button>

    <div class="detail-topbar__actions" role="group" aria-label="详情页操作">
      <button
        v-if="actions.canOpenHistory"
        class="detail-topbar__action detail-topbar__history"
        type="button"
        :aria-label="historyLabel ?? '历史记录'"
        @click="emit('open-history')"
      >
        <MarketDetailIcon name="history" />
        <span>{{ historyLabel ?? '历史记录' }}</span>
      </button>
      <button
        v-if="actions.canManageAlert"
        class="detail-topbar__action"
        type="button"
        aria-label="预警"
        @click="emit('open-alert')"
      >
        <MarketDetailIcon name="alert" />
        <span>预警</span>
      </button>

    </div>
  </header>
</template>

<style scoped>
.detail-topbar {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  align-items: center;
  gap: var(--gy-space-2);
  min-height: 48px;
  border-bottom: 1px solid var(--gy-border-subtle);
  background: var(--gy-bg-header);
}
.detail-topbar--without-back { grid-template-columns: minmax(0, 1fr) auto; }
.detail-topbar button { color: var(--gy-text-primary); font: inherit; }
.detail-topbar__back,
.detail-topbar__action,
.detail-topbar__identity {
  min-width: 44px;
  min-height: 36px;
  border: 0;
  border-radius: var(--gy-radius-md);
  background: transparent;
  cursor: pointer;
}
.detail-topbar__back { display: inline-flex; align-items: center; gap: var(--gy-space-1); padding: 0 var(--gy-space-2); white-space: nowrap; }
.detail-topbar__identity { display: flex; align-items: center; gap: var(--gy-space-2); min-width: 0; padding: 0 var(--gy-space-2); text-align: left; }
.detail-topbar__identity:hover,
.detail-topbar__action:hover,
.detail-topbar__back:hover { background: var(--gy-bg-hover); }
.detail-topbar button:focus-visible { outline: 2px solid var(--gy-border-focus); outline-offset: 2px; }
.detail-topbar__name { overflow: hidden; font-size: var(--gy-font-size-lg); font-weight: 700; text-overflow: ellipsis; white-space: nowrap; }
.detail-topbar__contract { color: var(--gy-text-muted); font-size: var(--gy-font-size-sm); white-space: nowrap; }
.detail-topbar__actions { display: flex; align-items: center; gap: var(--gy-space-1); }
.detail-topbar__action { display: inline-flex; align-items: center; justify-content: center; gap: var(--gy-space-1); padding: 0 var(--gy-space-3); }

@media (max-width: 640px) {
  .detail-topbar { min-height: 56px; }
  .detail-topbar__back,
  .detail-topbar__action,
  .detail-topbar__identity { min-height: 44px; }
  .detail-topbar__back span { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; }
  .detail-topbar__history span { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; }
  .detail-topbar__action { padding: 0 var(--gy-space-2); }
  .detail-topbar__contract { display: none; }
}
</style>
