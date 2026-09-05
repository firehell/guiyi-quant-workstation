<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'

import type { MarketDetailHistoryItem } from '@/types/marketDetail'
import MarketDetailDrawer from './MarketDetailDrawer.vue'

const props = defineProps<{
  tabs: readonly { id: string; label: string }[]
  activeId: string | null
  history: readonly MarketDetailHistoryItem[]
  historySelectable?: boolean
}>()

const emit = defineEmits<{
  select: [id: string]
  'history-select': [item: MarketDetailHistoryItem]
}>()

const mobile = ref(false)
const historyDrawerOpen = ref(false)
let media: MediaQueryList | null = null

function syncMedia(event: MediaQueryListEvent | MediaQueryList) {
  mobile.value = event.matches
  if (!mobile.value) historyDrawerOpen.value = false
}

function openHistory() {
  if (props.history.length === 0) return
  if (mobile.value) historyDrawerOpen.value = true
  else emit('select', 'history')
}

function selectHistory(item: MarketDetailHistoryItem) {
  if (!props.historySelectable) return
  historyDrawerOpen.value = false
  emit('history-select', item)
}

defineExpose({ openHistory })

onMounted(() => {
  media = window.matchMedia('(max-width: 480px)')
  syncMedia(media)
  media.addEventListener('change', syncMedia)
})
onBeforeUnmount(() => media?.removeEventListener('change', syncMedia))
</script>

<template>
  <section class="detail-section-tabs" data-detail-section="detail-tabs">
    <div class="detail-section-tabs__nav" role="tablist" aria-label="详情内容">
      <button
        v-for="tab in tabs"
        :key="tab.id"
        type="button"
        role="tab"
        :aria-selected="activeId === tab.id"
        :class="{ 'is-active': activeId === tab.id }"
        @click="emit('select', tab.id)"
      >{{ tab.label }}</button>
      <button
        v-if="history.length > 0"
        type="button"
        role="tab"
        :aria-selected="!mobile && activeId === 'history'"
        :class="{ 'is-active': !mobile && activeId === 'history' }"
        @click="openHistory"
      >历史记录</button>
    </div>

    <div class="detail-section-tabs__content">
      <slot :active-id="activeId" />
      <ol v-if="!mobile && activeId === 'history' && history.length > 0" class="detail-section-tabs__history">
        <li v-for="item in history" :key="item.id">
          <button v-if="historySelectable" type="button" @click="selectHistory(item)">
          <span>
            {{ item.label }}
            <small v-if="item.barEnd">
              · Bar {{ item.barEnd }} · 合约 {{ item.contract ?? '—' }}
              <template v-if="item.markerType"> · 类型 {{ item.markerType }}</template>
              <template v-if="item.formulaVersion"> · 公式 {{ item.formulaVersion }}</template>
              {{ item.notificationAttemptedAt ? ' · 已尝试通知' : '' }}
            </small>
          </span>
          <time :datetime="item.occurredAt">{{ item.timeLabel ?? item.occurredAt }}</time>
          </button>
          <template v-else>
          <span>
            {{ item.label }}
            <small v-if="item.barEnd">
              · Bar {{ item.barEnd }} · 合约 {{ item.contract ?? '—' }}
              <template v-if="item.markerType"> · 类型 {{ item.markerType }}</template>
              <template v-if="item.formulaVersion"> · 公式 {{ item.formulaVersion }}</template>
              {{ item.notificationAttemptedAt ? ' · 已尝试通知' : '' }}
            </small>
          </span>
          <time :datetime="item.occurredAt">{{ item.timeLabel ?? item.occurredAt }}</time>
          </template>
        </li>
      </ol>
    </div>

    <MarketDetailDrawer :open="historyDrawerOpen" title="历史记录" @close="historyDrawerOpen = false">
      <ol class="detail-section-tabs__history">
        <li v-for="item in history" :key="item.id">
          <button v-if="historySelectable" type="button" @click="selectHistory(item)">
          <span>
            {{ item.label }}
            <small v-if="item.barEnd">
              · Bar {{ item.barEnd }} · 合约 {{ item.contract ?? '—' }}
              <template v-if="item.markerType"> · 类型 {{ item.markerType }}</template>
              <template v-if="item.formulaVersion"> · 公式 {{ item.formulaVersion }}</template>
              {{ item.notificationAttemptedAt ? ' · 已尝试通知' : '' }}
            </small>
          </span>
          <time :datetime="item.occurredAt">{{ item.timeLabel ?? item.occurredAt }}</time>
          </button>
          <template v-else>
          <span>
            {{ item.label }}
            <small v-if="item.barEnd">
              · Bar {{ item.barEnd }} · 合约 {{ item.contract ?? '—' }}
              <template v-if="item.markerType"> · 类型 {{ item.markerType }}</template>
              <template v-if="item.formulaVersion"> · 公式 {{ item.formulaVersion }}</template>
              {{ item.notificationAttemptedAt ? ' · 已尝试通知' : '' }}
            </small>
          </span>
          <time :datetime="item.occurredAt">{{ item.timeLabel ?? item.occurredAt }}</time>
          </template>
        </li>
      </ol>
    </MarketDetailDrawer>
  </section>
</template>

<style scoped>
.detail-section-tabs { border-top: 1px solid var(--gy-border-subtle); }
.detail-section-tabs__nav { display: flex; align-items: center; gap: var(--gy-space-1); overflow-x: auto; padding: var(--gy-space-3) 0; }
.detail-section-tabs__nav button { min-height: 44px; padding: 0 var(--gy-space-3); border: 0; border-bottom: 2px solid transparent; color: var(--gy-text-muted); background: transparent; font: inherit; white-space: nowrap; cursor: pointer; }
.detail-section-tabs__nav button:hover { color: var(--gy-text-primary); background: var(--gy-bg-hover); }
.detail-section-tabs__nav button:focus-visible { outline: 2px solid var(--gy-border-focus); outline-offset: -2px; }
.detail-section-tabs__nav button.is-active { border-bottom-color: var(--gy-detail-accent); color: var(--gy-text-primary); font-weight: 700; }
.detail-section-tabs__content { min-height: 72px; padding-bottom: var(--gy-space-4); }
.detail-section-tabs__history { display: grid; gap: var(--gy-space-2); margin: 0; padding: 0; list-style: none; }
.detail-section-tabs__history li { display: flex; justify-content: space-between; gap: var(--gy-space-3); padding: var(--gy-space-3); border-radius: var(--gy-radius-md); background: var(--gy-detail-section-bg); }
.detail-section-tabs__history li > button { display: flex; width: 100%; justify-content: space-between; gap: var(--gy-space-3); padding: 0; border: 0; color: inherit; background: transparent; font: inherit; text-align: left; cursor: pointer; }
.detail-section-tabs__history time { color: var(--gy-text-muted); font-size: var(--gy-font-size-sm); white-space: nowrap; }
.detail-section-tabs__history small { color: var(--gy-text-muted); font-size: var(--gy-font-size-sm); }
</style>
