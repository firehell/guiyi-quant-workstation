<script setup lang="ts">
import { computed, ref, useId, watch } from 'vue'

import type { MarketDetailDisclosureSection, MarketDetailHeaderModel } from '@/types/marketDetail'
import MarketDetailIcon from './MarketDetailIcon.vue'

const props = defineProps<{
  identityKey: string
  sections: readonly MarketDetailDisclosureSection[]
  freshness: MarketDetailHeaderModel['freshness']
}>()

const open = ref(false)
const contentId = `market-facts-${useId()}`
const freshnessLabel = computed(() => props.freshness === 'fresh' ? '正常' : props.freshness === 'stale' ? '旧快照' : '不可用')

watch(() => props.identityKey, () => { open.value = false })
</script>

<template>
  <div class="facts-disclosure" :class="`facts-disclosure--${freshness}`">
    <button
      type="button"
      :aria-expanded="open"
      :aria-controls="contentId"
      @click="open = !open"
    >
      <span>更多行情数据</span>
      <span class="facts-disclosure__state">{{ freshnessLabel }}</span>
      <MarketDetailIcon :name="open ? 'chevron-down' : 'chevron-right'" :size="18" />
    </button>
    <div v-if="open" :id="contentId" class="facts-disclosure__content">
      <section v-for="section in sections" :key="section.id">
        <div class="facts-disclosure__heading">
          <h3>{{ section.title }}</h3>
          <span>{{ section.summary }}</span>
        </div>
        <dl>
          <div v-for="row in section.rows" :key="`${section.id}-${row.label}`">
            <dt>{{ row.label }}</dt>
            <dd>{{ row.value }}</dd>
          </div>
        </dl>
      </section>
      <p v-if="sections.length === 0" class="facts-disclosure__empty">暂无更多行情数据</p>
    </div>
  </div>
</template>

<style scoped>
.facts-disclosure { margin-top: var(--gy-space-3); border: 1px solid var(--gy-border); border-radius: var(--gy-radius-lg); background: var(--gy-detail-card-bg); }
.facts-disclosure--stale { border-color: var(--gy-detail-warning-border); }
.facts-disclosure--unavailable { border-color: color-mix(in srgb, var(--gy-status-error) 35%, transparent); }
.facts-disclosure > button { display: grid; grid-template-columns: 1fr auto auto; align-items: center; gap: var(--gy-space-2); width: 100%; min-height: 44px; padding: 0 var(--gy-space-3); border: 0; border-radius: inherit; color: var(--gy-text-primary); background: transparent; font: inherit; font-weight: 600; text-align: left; cursor: pointer; }
.facts-disclosure > button:hover { background: var(--gy-bg-hover); }
.facts-disclosure > button:focus-visible { outline: 2px solid var(--gy-border-focus); outline-offset: 2px; }
.facts-disclosure__state { color: var(--gy-text-muted); font-size: var(--gy-font-size-sm); font-weight: 500; }
.facts-disclosure--stale .facts-disclosure__state { color: var(--gy-status-warning); }
.facts-disclosure--unavailable .facts-disclosure__state { color: var(--gy-status-error); }
.facts-disclosure__content { display: grid; gap: var(--gy-space-3); padding: 0 var(--gy-space-3) var(--gy-space-3); }
.facts-disclosure__heading { display: flex; align-items: baseline; justify-content: space-between; gap: var(--gy-space-3); }
.facts-disclosure h3 { margin: 0; color: var(--gy-text-primary); font-size: var(--gy-font-size-md); }
.facts-disclosure__heading span { color: var(--gy-text-muted); font-size: var(--gy-font-size-sm); }
.facts-disclosure dl { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: var(--gy-space-2); margin: var(--gy-space-2) 0 0; }
.facts-disclosure dl div { display: flex; justify-content: space-between; gap: var(--gy-space-2); }
.facts-disclosure dt { color: var(--gy-text-muted); }
.facts-disclosure dd { margin: 0; color: var(--gy-text-primary); text-align: right; }
.facts-disclosure__empty { margin: 0; color: var(--gy-text-muted); }

@media (max-width: 480px) {
  .facts-disclosure dl { grid-template-columns: 1fr; }
}
</style>
