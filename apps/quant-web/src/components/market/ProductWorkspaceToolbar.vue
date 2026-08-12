<script setup lang="ts">
import { computed } from 'vue'
import {
  NButton,
  NButtonGroup,
  NCheckbox,
  NCheckboxGroup,
  NInput,
  NPopover,
  NSelect,
} from 'naive-ui'
import type { DominantContractItem, MainIndicatorId, MarketFrequency, SeriesKind } from '@/types/market'
import { MARKET_FREQUENCIES } from '@/types/market'
import { MAIN_INDICATOR_DEFINITIONS } from '@/utils/mainIndicators'

const props = defineProps<{
  symbol: string
  seriesKind: SeriesKind
  frequency: MarketFrequency
  contract: string
  dominants: DominantContractItem[]
  visibleMainIndicators: MainIndicatorId[]
  fullscreen: boolean
}>()

const emit = defineEmits<{
  'update:symbol': [value: string]
  'update:series-kind': [value: SeriesKind]
  'update:frequency': [value: MarketFrequency]
  'update:contract': [value: string]
  'update:visible-main-indicators': [value: MainIndicatorId[]]
  'open-research': []
  'toggle-fullscreen': []
  back: []
}>()

const symbolOptions = computed(() => props.dominants.map((item) => ({
  label: `${item.product.toUpperCase()} ${item.product_name}`,
  value: item.product,
})))
const indicatorOptions = MAIN_INDICATOR_DEFINITIONS
  .filter((item) => item.available)
  .map((item) => ({ label: item.displayName, value: item.id, capability: item.capability }))

function periodLabel(value: MarketFrequency) {
  return value === '1d' ? 'D' : value === '1w' ? 'W' : value
}

function updateIndicators(value: Array<string | number>) {
  const ids = value.filter((item): item is MainIndicatorId => indicatorOptions.some((option) => option.value === item))
  emit('update:visible-main-indicators', ids)
}
</script>

<template>
  <div class="product-workspace-toolbar">
    <NButton quaternary size="small" class="toolbar__back" @click="emit('back')">市场</NButton>
    <NSelect
      :value="symbol"
      :options="symbolOptions"
      filterable
      size="small"
      class="toolbar__symbol"
      aria-label="品种"
      @update:value="emit('update:symbol', $event)"
    />
    <NButtonGroup size="small" class="toolbar__series">
      <NButton
        :type="seriesKind === 'actual_dominant' ? 'primary' : 'default'"
        @click="emit('update:series-kind', 'actual_dominant')"
      >真实主力</NButton>
      <NButton
        :type="seriesKind === 'continuous' ? 'primary' : 'default'"
        @click="emit('update:series-kind', 'continuous')"
      >主连</NButton>
    </NButtonGroup>
    <NButtonGroup size="small" class="toolbar__periods" aria-label="周期">
      <NButton
        v-for="item in MARKET_FREQUENCIES"
        :key="item"
        :type="frequency === item ? 'primary' : 'default'"
        @click="emit('update:frequency', item)"
      >{{ periodLabel(item) }}</NButton>
    </NButtonGroup>
    <NPopover trigger="click" placement="bottom-start">
      <template #trigger><NButton size="small" secondary>指标</NButton></template>
      <NCheckboxGroup
        :value="visibleMainIndicators"
        class="toolbar__indicator-menu"
        @update:value="updateIndicators"
      >
        <NCheckbox v-for="item in indicatorOptions" :key="item.value" :value="item.value">
          {{ item.label }}
          <small v-if="item.capability === 'observation_overlay'">仅观察 · 重绘风险</small>
        </NCheckbox>
      </NCheckboxGroup>
    </NPopover>
    <NPopover trigger="click" placement="bottom-end">
      <template #trigger><NButton size="small" tertiary>高级</NButton></template>
      <div class="toolbar__advanced">
        <span>指定真实合约</span>
        <NInput
          :value="contract"
          size="small"
          placeholder="例如 JM2601"
          @update:value="emit('update:contract', $event.toUpperCase())"
        />
        <NButton size="small" :type="seriesKind === 'contract' ? 'primary' : 'default'" @click="emit('update:series-kind', 'contract')">
          使用指定合约
        </NButton>
      </div>
    </NPopover>
    <div class="toolbar__spacer" />
    <NButton size="small" secondary class="toolbar__research" @click="emit('open-research')">研究</NButton>
    <NButton size="small" secondary @click="emit('toggle-fullscreen')">
      {{ fullscreen ? '退出全屏' : '全屏' }}
    </NButton>
  </div>
</template>

<style scoped>
.product-workspace-toolbar { display: flex; align-items: center; gap: 8px; min-width: 0; flex-wrap: wrap; }
.toolbar__symbol { width: 184px; }
.toolbar__series, .toolbar__periods { white-space: nowrap; }
.toolbar__spacer { flex: 1 1 8px; }
.toolbar__indicator-menu { display: grid; gap: 8px; padding: 4px; min-width: 172px; }
.toolbar__indicator-menu small { display: block; margin-top: 2px; color: var(--gy-text-muted); font-size: var(--gy-font-size-xs); }
.toolbar__advanced { display: grid; gap: 8px; width: 196px; padding: 4px; }
.toolbar__advanced > span { color: var(--gy-text-muted); font-size: var(--gy-font-size-sm); }

@media (max-width: 860px) {
  .toolbar__back { display: none; }
  .toolbar__symbol { width: min(184px, calc(100vw - 62px)); }
  .toolbar__spacer { display: none; }
}
</style>
