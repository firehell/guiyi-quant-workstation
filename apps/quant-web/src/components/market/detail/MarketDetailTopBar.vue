<script setup lang="ts">
import MarketDetailIcon from './MarketDetailIcon.vue'

defineProps<{
  productName: string
  symbol: string
  displayContract: string | null
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
  'open-more': []
}>()
</script>

<template>
  <header class="detail-topbar" data-detail-section="topbar">
    <button class="detail-topbar__icon-button" type="button" aria-label="返回" @click="emit('back')">
      <MarketDetailIcon name="back" />
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
        aria-label="历史记录"
        @click="emit('open-history')"
      >
        <MarketDetailIcon name="history" />
        <span>历史</span>
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
      <button class="detail-topbar__icon-button" type="button" aria-label="更多" @click="emit('open-more')">
        <MarketDetailIcon name="more" />
      </button>
    </div>
  </header>
</template>

<style scoped>
.detail-topbar {
  display: grid;
  grid-template-columns: 44px minmax(0, 1fr) auto;
  align-items: center;
  gap: var(--gy-space-2);
  min-height: 56px;
  border-bottom: 1px solid var(--gy-border-subtle);
  background: var(--gy-bg-header);
}
.detail-topbar button { color: var(--gy-text-primary); font: inherit; }
.detail-topbar__icon-button,
.detail-topbar__action,
.detail-topbar__identity {
  min-width: 44px;
  min-height: 44px;
  border: 0;
  border-radius: var(--gy-radius-md);
  background: transparent;
  cursor: pointer;
}
.detail-topbar__icon-button { display: inline-grid; place-items: center; }
.detail-topbar__identity { display: flex; align-items: center; gap: var(--gy-space-2); min-width: 0; padding: 0 var(--gy-space-2); text-align: left; }
.detail-topbar__identity:hover,
.detail-topbar__action:hover,
.detail-topbar__icon-button:hover { background: var(--gy-bg-hover); }
.detail-topbar button:focus-visible { outline: 2px solid var(--gy-border-focus); outline-offset: 2px; }
.detail-topbar__name { overflow: hidden; font-size: var(--gy-font-size-lg); font-weight: 700; text-overflow: ellipsis; white-space: nowrap; }
.detail-topbar__contract { color: var(--gy-text-muted); font-size: var(--gy-font-size-sm); white-space: nowrap; }
.detail-topbar__actions { display: flex; align-items: center; gap: var(--gy-space-1); }
.detail-topbar__action { display: inline-flex; align-items: center; justify-content: center; gap: var(--gy-space-1); padding: 0 var(--gy-space-3); }

@media (max-width: 640px) {
  .detail-topbar__history span { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; }
  .detail-topbar__action { padding: 0 var(--gy-space-2); }
  .detail-topbar__contract { display: none; }
}
</style>
